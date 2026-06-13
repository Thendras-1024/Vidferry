@app.route('/published-materials', methods=['GET'])
def published_materials():
    try:
        limit = int(request.args.get("limit", 50))
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_published_youtube_materials(limit)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取已发布素材失败: {str(e)}", "data": None}), 500


@app.route('/publish/tasks', methods=['GET'])
def publish_tasks():
    try:
        limit = int(request.args.get("limit", 20))
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": list_publish_tasks(limit)
        }), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"获取发布任务失败: {str(e)}", "data": None}), 500


@app.route('/publish/target-records/<int:record_id>', methods=['DELETE'])
def delete_publish_target(record_id):
    try:
        return jsonify({
            "code": 200,
            "msg": "已删除本地发布记录，平台上的已发布视频不会被删除。",
            "data": delete_publish_target_record(record_id)
        }), 200
    except LookupError as e:
        return jsonify({"code": 404, "msg": str(e), "data": None}), 404
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
    except Exception as e:
        return jsonify({"code": 500, "msg": f"删除发布记录失败: {str(e)}", "data": None}), 500
