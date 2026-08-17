@app.route('/deleteFile', methods=['DELETE'])
def delete_file():
    payload = request.get_json(silent=True) or {}
    file_id = payload.get('id') or request.args.get('id')

    if not file_id or not file_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing file ID",
            "data": None
        }), 400

    try:
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()

            data = delete_material_record(cursor, int(file_id), _current_account_owner_id())
            conn.commit()

        backend_logger.info("素材已删除 material_id=%s source_type=%s", file_id, data.get("sourceType", ""))
        return jsonify({
            "code": 200,
            "msg": "File deleted successfully",
            "data": _redact_public_paths(data)
        }), 200

    except LookupError as e:
        return jsonify({
            "code": 404,
            "msg": str(e),
            "data": None
        }), 404

    except WorkflowConflictError as e:
        return jsonify({
            "code": 409,
            "msg": str(e),
            "data": {
                "errorCode": e.error_code,
                "errorType": e.error_type,
                **e.data,
            }
        }), 409

    except Exception:
        backend_logger.exception("删除素材失败 material_id=%s", file_id)
        return jsonify({
            "code": 500,
            "msg": str("delete failed!"),
            "data": None
        }), 500


@app.route('/deleteFiles', methods=['POST'])
def batch_delete_files():
    try:
        payload = request.get_json(silent=True) or {}
        file_ids = [
            int(item)
            for item in (payload.get("ids") or payload.get("fileIds") or [])
            if str(item).isdigit()
        ]
        if not file_ids:
            return jsonify({"code": 400, "msg": "请选择要删除的素材", "data": None}), 400
        backend_logger.info("批量删除素材开始 count=%s", len(file_ids))
        result = delete_material_records(file_ids, _current_account_owner_id())
        backend_logger.info("批量删除素材完成 count=%s", len(result))
        return jsonify({
            "code": 200,
            "msg": "Files deleted",
            "data": _redact_public_paths(result)
        }), 200
    except Exception:
        backend_logger.exception("批量删除素材失败")
        return jsonify({"code": 500, "msg": "批量删除素材失败，请稍后重试", "data": None}), 500
