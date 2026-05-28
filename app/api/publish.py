@app.route('/postVideo', methods=['POST'])
def postVideo():
    data = request.get_json()
    try:
        result = _publish_payload(data)
    except WorkflowConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc), "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data}}), 409
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception as e:
        print(f"发布视频时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"发布失败: {str(e)}",
            "data": None,
        }), 500
    failed_count = result.get("failedCount", 0)
    success_count = result.get("successCount", 0)
    return jsonify({
        "code": 200,
        "msg": "所有平台发布失败" if failed_count and success_count == 0 else ("部分平台发布失败" if failed_count else "发布任务已提交"),
        "data": result,
    }), 200


@app.route('/updateUserinfo', methods=['POST'])
def updateUserinfo():
    # 获取JSON数据
    data = request.get_json()

    # 从JSON数据中提取 type 和 userName
    user_id = data.get('id')
    type = data.get('type')
    userName = data.get('userName')
    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 更新数据库记录
            cursor.execute('''
                           UPDATE user_info
                           SET type     = ?,
                               userName = ?
                           WHERE id = ?;
                           ''', (type, userName, user_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account update successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("update failed!"),
            "data": None
        }), 500

@app.route('/postVideoBatch', methods=['POST'])
def postVideoBatch():
    data_list = request.get_json()

    if not isinstance(data_list, list):
        return jsonify({"code": 400, "msg": "Expected a JSON array", "data": None}), 400
    batch_results = []
    for index, data in enumerate(data_list):
        try:
            batch_results.append({
                "index": index,
                "status": "success",
                "data": _publish_payload(data),
            })
        except WorkflowConflictError as exc:
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": str(exc),
                "data": {"errorCode": exc.error_code, "errorType": exc.error_type, **exc.data},
            })
        except Exception as exc:
            batch_results.append({
                "index": index,
                "status": "failed",
                "message": str(exc),
                "data": None,
            })
    failed_count = sum(1 for item in batch_results if item["status"] != "success" or item["data"].get("hasFailures"))
    return jsonify({
        "code": 200,
        "msg": "部分批次发布失败" if failed_count else "发布任务已提交",
        "data": {
            "items": batch_results,
            "hasFailures": failed_count > 0,
        }
    }), 200


@app.route('/bilibili/categories', methods=['GET'])
def get_bilibili_categories():
    return jsonify({
        "code": 200,
        "msg": "success",
        "data": {
            "items": bilibili_categories(),
            "defaultTid": BILIBILI_DEFAULT_TID,
        },
    }), 200

# Cookie文件上传API
