@app.route('/deleteFile', methods=['GET'])
def delete_file():
    file_id = request.args.get('id')

    if not file_id or not file_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing file ID",
            "data": None
        }), 400

    try:
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            data = delete_material_record(cursor, int(file_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "File deleted successfully",
            "data": data
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
        return jsonify({
            "code": 200,
            "msg": "Files deleted",
            "data": delete_material_records(file_ids)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"batch delete failed: {str(e)}", "data": None}), 500
