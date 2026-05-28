@app.route("/getAccounts", methods=['GET'])
def getAccounts():
    """快速获取所有账号信息，不进行cookie验证"""
    try:
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM user_info''')
            rows = cursor.fetchall()
            rows_list = [list(row) for row in rows]

            print("\n📋 当前数据表内容（快速获取）：")
            for row in rows:
                print(row)

            return jsonify(
                {
                    "code": 200,
                    "msg": None,
                    "data": rows_list
                }), 200
    except Exception as e:
        print(f"获取账号列表时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"获取账号列表失败: {str(e)}",
            "data": None
        }), 500


@app.route("/getValidAccounts",methods=['GET'])
async def getValidAccounts():
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        SELECT * FROM user_info''')
        rows = cursor.fetchall()
        rows_list = [list(row) for row in rows]
        print("\n📋 当前数据表内容：")
        for row in rows:
            print(row)
        for row in rows_list:
            flag = await check_cookie(row[1],row[2])
            if not flag:
                row[4] = 0
                cursor.execute('''
                UPDATE user_info
                SET status = ?
                WHERE id = ?
                ''', (0,row[0]))
                conn.commit()
                print("✅ 用户状态已更新")
        for row in rows:
            print(row)
        return jsonify(
                        {
                            "code": 200,
                            "msg": None,
                            "data": rows_list
                        }),200

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
        # 获取数据库连接
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

    except Exception as e:
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


@app.route('/deleteAccount', methods=['GET'])
def delete_account():
    account_id = request.args.get('id')

    if not account_id or not account_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing account ID",
            "data": None
        }), 400

    account_id = int(account_id)

    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询要删除的记录
            cursor.execute("SELECT * FROM user_info WHERE id = ?", (account_id,))
            record = cursor.fetchone()

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "account not found",
                    "data": None
                }), 404

            record = dict(record)

            # 删除关联的cookie文件
            if record.get('filePath'):
                cookie_file_path = Path(BASE_DIR / "cookiesFile" / record['filePath'])
                if cookie_file_path.exists():
                    try:
                        cookie_file_path.unlink()
                        print(f"✅ Cookie文件已删除: {cookie_file_path}")
                    except Exception as e:
                        print(f"⚠️ 删除Cookie文件失败: {e}")

            # 删除数据库记录
            cursor.execute("DELETE FROM user_info WHERE id = ?", (account_id,))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account deleted successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"delete failed: {str(e)}",
            "data": None
        }), 500


@app.route('/account', methods=['POST'])
def create_account():
    try:
        data = request.get_json(silent=True) or {}
        platform_type = int(data.get("type") or 0)
        user_name = (data.get("userName") or data.get("name") or "").strip()
        file_path = (data.get("filePath") or "").strip()
        status = int(data.get("status") if data.get("status") is not None else 0)
        if platform_type not in {1, 2, 3, 4, 5}:
            return jsonify({"code": 400, "msg": "不支持的平台类型", "data": None}), 400
        if not user_name:
            return jsonify({"code": 400, "msg": "账号名称不能为空", "data": None}), 400
        if not file_path:
            file_prefix_map = {
                1: "xiaohongshu",
                2: "tencent",
                3: "douyin",
                4: "kuaishou",
                5: "bilibili",
            }
            safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", user_name).strip("_") or uuid.uuid4().hex
            file_path = f"{file_prefix_map[platform_type]}_{safe_name}.json"

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
            ''', (platform_type, file_path, user_name, status))
            conn.commit()
            account_id = cursor.lastrowid

        return jsonify({
            "code": 200,
            "msg": "account created successfully",
            "data": [account_id, platform_type, file_path, user_name, status]
        }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"account create failed: {str(e)}",
            "data": None
        }), 500
