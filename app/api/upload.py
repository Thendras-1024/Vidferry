"""素材上传、列表与受 owner 保护的内容读取接口。"""


_UPLOAD_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"}
_UPLOAD_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_PUBLIC_PATH_FIELDS = {
    "filePath", "file_path", "path", "storageKey", "storage_key", "localThumbnailPath",
    "sourceFilePath", "processedFilePath", "downloadedFilePath", "transcriptFilePath",
    "editingBodyPath", "editingAssPath", "publishCommand", "errorDetail",
}


def _redact_public_paths(value):
    if isinstance(value, list):
        return [_redact_public_paths(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _redact_public_paths(item)
            for key, item in value.items()
            if key not in _PUBLIC_PATH_FIELDS
        }
    return value


@app.errorhandler(413)
def upload_too_large(_error):
    return jsonify({
        "code": 413,
        "msg": f"上传文件不能超过 {USER_UPLOAD_MAX_MB} MB",
        "data": {"errorCode": "VF-UPLOAD-FILE-TOO-LARGE"},
    }), 413


def _validate_uploaded_media(file_path):
    suffix = file_path.suffix.lower()
    if suffix in _UPLOAD_VIDEO_EXTENSIONS:
        duration_seconds = _get_media_duration_seconds(file_path)
        if duration_seconds <= 0:
            raise ValueError("无法解析上传的视频")
        return duration_seconds
    if suffix in _UPLOAD_IMAGE_EXTENSIONS:
        from PIL import Image

        with Image.open(file_path) as image:
            image.verify()
        return 0
    raise ValueError("不支持的媒体文件类型")


def _assert_user_storage_quota(cursor, owner_user_id, incoming_size_mb):
    cursor.execute("LOCK TABLE file_records IN SHARE ROW EXCLUSIVE MODE")
    cursor.execute(
        "SELECT COALESCE(SUM(filesize), 0) AS total_mb FROM file_records WHERE owner_user_id = %s",
        (owner_user_id,),
    )
    total_mb = float(cursor.fetchone()["total_mb"] or 0)
    if total_mb + incoming_size_mb > USER_STORAGE_QUOTA_MB:
        raise ValueError("用户素材空间已满")


def _owned_asset_path(asset_id, owner_user_id):
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM file_records WHERE asset_id = %s AND owner_user_id = %s",
            (asset_id, owner_user_id),
        )
        row = cursor.fetchone()
    if not row:
        raise LookupError("素材不存在")

    resolved = _material_file_path(dict(row))
    if not resolved:
        raise LookupError("素材不存在")
    resolved = resolved.resolve()
    allowed_roots = (
        Path(BASE_DIR / "videoFile").resolve(),
        Path(YOUTUBE_DOWNLOAD_DIR).resolve(),
        Path(YOUTUBE_PROCESSED_DIR).resolve(),
    )
    if not any(resolved.is_relative_to(root) for root in allowed_roots) or not resolved.is_file():
        raise LookupError("素材不存在")
    return resolved


@app.route('/assets/<asset_id>/content', methods=['GET'])
def get_asset_content(asset_id):
    try:
        file_path = _owned_asset_path(asset_id, _current_account_owner_id())
        return send_from_directory(
            str(file_path.parent),
            file_path.name,
            as_attachment=request.args.get("download") == "1",
            conditional=True,
        )
    except LookupError:
        return jsonify({"code": 404, "msg": "素材不存在", "data": None}), 404


@app.route('/upload', methods=['POST'])
@app.route('/uploadSave', methods=['POST'])
def upload_save():
    if 'file' not in request.files:
        return jsonify({"code": 400, "data": None, "msg": "No file part in the request"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"code": 400, "data": None, "msg": "No selected file"}), 400

    owner_user_id = _current_account_owner_id()
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _UPLOAD_VIDEO_EXTENSIONS | _UPLOAD_IMAGE_EXTENSIONS:
        return jsonify({"code": 400, "msg": "不支持的媒体文件类型", "data": None}), 400

    custom_filename = request.form.get('filename')
    filename = f"{_safe_filename(custom_filename)}{suffix}" if custom_filename else _safe_filename(file.filename)
    filepath = None
    try:
        asset_id = uuid.uuid4().hex
        final_filename = f"{asset_id}{suffix}"
        owner_dir = Path(BASE_DIR / "videoFile" / str(int(owner_user_id)))
        owner_dir.mkdir(parents=True, exist_ok=True)
        filepath = _safe_child_path(owner_dir, final_filename)
        storage_key = f"{owner_user_id}/{final_filename}"
        file.save(filepath)

        duration_seconds = _validate_uploaded_media(filepath)
        duration_label = _format_duration_label(duration_seconds)
        filesize_mb = round(float(os.path.getsize(filepath)) / (1024 * 1024), 2)
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            _assert_user_storage_quota(cursor, owner_user_id, filesize_mb)
            cursor.execute('''
            INSERT INTO file_records (
                owner_user_id, asset_id, filename, original_filename, filesize, file_path, storage_key,
                storage_backend, source_type, status, duration, duration_seconds, metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                owner_user_id,
                asset_id,
                filename,
                file.filename,
                filesize_mb,
                storage_key,
                storage_key,
                "local",
                "manual_upload",
                "ready",
                duration_label,
                round(float(duration_seconds or 0), 2),
                json.dumps({"originalUploadName": file.filename}, ensure_ascii=False),
            ))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "File uploaded and saved successfully",
            "data": {
                "assetId": asset_id,
                "filename": filename,
                "contentUrl": f"/assets/{asset_id}/content",
            },
        }), 200
    except ValueError as exc:
        if filepath:
            safe_unlink(filepath)
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        if filepath:
            safe_unlink(filepath)
        print(f"upload failed : errorType = {type(exc).__name__}")
        return jsonify({"code": 500, "msg": "上传失败", "data": None}), 500


@app.route('/getFiles', methods=['GET'])
def get_all_files():
    try:
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": _redact_public_paths(list_material_records(request.args, _current_account_owner_id())),
        }), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        print(f"get materials failed : errorType = {type(exc).__name__}")
        return jsonify({"code": 500, "msg": "获取素材失败", "data": None}), 500
