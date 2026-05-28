@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400
    try:
        # 保存文件到指定位置
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        filepath = Path(BASE_DIR / "videoFile" / f"{uuid_v1}_{file.filename}")
        file.save(filepath)
        return jsonify({"code":200,"msg": "File uploaded successfully", "data": f"{uuid_v1}_{file.filename}"}), 200
    except Exception as e:
        return jsonify({"code":500,"msg": str(e),"data":None}), 500

@app.route('/getFile', methods=['GET'])
def get_file():
    # 获取 filename 参数
    filename = request.args.get('filename')

    if not filename:
        return jsonify({"code": 400, "msg": "filename is required", "data": None}), 400

    candidate = Path(filename)
    if candidate.is_absolute():
        allowed_roots = [
            Path(BASE_DIR / "videoFile").resolve(),
            Path(YOUTUBE_DOWNLOAD_DIR).resolve(),
            Path(YOUTUBE_PROCESSED_DIR).resolve(),
        ]
        resolved = candidate.resolve()
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            return jsonify({"code": 400, "msg": "Invalid filename", "data": None}), 400
        if not resolved.is_file():
            return jsonify({"code": 404, "msg": "File not found", "data": None}), 404
        return send_from_directory(str(resolved.parent), resolved.name)

    # 防止路径穿越攻击
    if '..' in filename or filename.startswith('/'):
        return jsonify({"code": 400, "msg": "Invalid filename", "data": None}), 400

    # 拼接完整路径
    file_path = str(Path(BASE_DIR / "videoFile"))

    # 返回文件
    return send_from_directory(file_path,filename)


@app.route('/uploadSave', methods=['POST'])
def upload_save():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400

    # 获取表单中的自定义文件名（可选）
    custom_filename = request.form.get('filename', None)
    if custom_filename:
        filename = custom_filename + "." + file.filename.split('.')[-1]
    else:
        filename = file.filename

    try:
        asset_id = uuid.uuid4().hex
        suffix = Path(filename).suffix or Path(file.filename).suffix
        final_filename = f"{asset_id}{suffix}"
        filepath = Path(BASE_DIR / "videoFile" / final_filename)

        # 保存文件
        file.save(filepath)
        duration_seconds = 0
        duration_label = ""
        if filepath.suffix.lower() in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"}:
            try:
                duration_seconds = _get_media_duration_seconds(filepath)
                duration_label = _format_duration_label(duration_seconds)
            except Exception:
                duration_seconds = 0

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO file_records (
                asset_id, filename, original_filename, filesize, file_path, storage_key,
                storage_backend, source_type, status, duration, duration_seconds, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                asset_id,
                filename,
                file.filename,
                round(float(os.path.getsize(filepath)) / (1024 * 1024), 2),
                final_filename,
                final_filename,
                "local",
                "manual_upload",
                "ready",
                duration_label,
                round(float(duration_seconds or 0), 2),
                json.dumps({"originalUploadName": file.filename}, ensure_ascii=False),
            ))
            conn.commit()
            print("✅ 上传文件已记录")

        return jsonify({
            "code": 200,
            "msg": "File uploaded and saved successfully",
            "data": {
                "filename": filename,
                "filepath": final_filename
            }
        }), 200

    except Exception as e:
        print(f"Upload failed: {e}")
        return jsonify({
            "code": 500,
            "msg": f"upload failed: {e}",
            "data": None
        }), 500

@app.route('/getFiles', methods=['GET'])
def get_all_files():
    try:
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_material_records(request.args)
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"get file failed: {e}",
            "data": None
        }), 500


