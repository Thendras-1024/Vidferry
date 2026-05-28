@app.route('/uploadCookie', methods=['POST'])
def upload_cookie():
    try:
        if 'file' not in request.files:
            return jsonify({
                "code": 400,
                "msg": "没有找到Cookie文件",
                "data": None
            }), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({
                "code": 400,
                "msg": "Cookie文件名不能为空",
                "data": None
            }), 400

        if not file.filename.endswith('.json'):
            return jsonify({
                "code": 400,
                "msg": "Cookie文件必须是JSON格式",
                "data": None
            }), 400

        # 获取账号信息
        account_id = request.form.get('id')
        platform = request.form.get('platform')

        if not account_id or not account_id.isdigit() or not platform:
            return jsonify({
                "code": 400,
                "msg": "缺少账号ID或平台信息",
                "data": None
            }), 400

        platform_type_map = {
            '小红书': 1,
            '视频号': 2,
            '抖音': 3,
            '快手': 4,
            'B站': 5,
            '哔哩哔哩': 5,
            'Bilibili': 5,
        }
        platform_type = platform_type_map.get(platform)
        if not platform_type:
            return jsonify({
                "code": 400,
                "msg": "不支持的平台类型",
                "data": None
            }), 400

        # 从数据库获取账号的文件路径
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT type, filePath FROM user_info WHERE id = ?', (account_id,))
            result = cursor.fetchone()

            if not result:
                return jsonify({
                    "code": 404,
                    "msg": "账号不存在",
                    "data": None
                }), 404

            if int(result['type']) != platform_type:
                return jsonify({
                    "code": 400,
                    "msg": "上传平台与账号平台不匹配",
                    "data": None
                }), 400

            # 保存上传的Cookie文件到对应路径
            cookie_file_path = Path(BASE_DIR / "cookiesFile" / result['filePath'])
            cookie_file_path.parent.mkdir(parents=True, exist_ok=True)

            file.save(str(cookie_file_path))

            cursor.execute('UPDATE user_info SET status = ? WHERE id = ?', (1, account_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "Cookie文件上传成功",
            "data": None
        }), 200

    except Exception as e:
        print(f"上传Cookie文件时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"上传Cookie文件失败: {str(e)}",
            "data": None
        }), 500


# Cookie文件下载API
@app.route('/downloadCookie', methods=['GET'])
def download_cookie():
    try:
        file_path = request.args.get('filePath')
        if not file_path:
            return jsonify({
                "code": 500,
                "msg": "缺少文件路径参数",
                "data": None
            }), 400

        # 验证文件路径的安全性，防止路径遍历攻击
        cookie_file_path = Path(BASE_DIR / "cookiesFile" / file_path).resolve()
        base_path = Path(BASE_DIR / "cookiesFile").resolve()

        if not cookie_file_path.is_relative_to(base_path):
            return jsonify({
                "code": 500,
                "msg": "非法文件路径",
                "data": None
            }), 400

        if not cookie_file_path.exists():
            return jsonify({
                "code": 500,
                "msg": "Cookie文件不存在",
                "data": None
            }), 404

        # 返回文件
        return send_from_directory(
            directory=str(cookie_file_path.parent),
            path=cookie_file_path.name,
            as_attachment=True
        )

    except Exception as e:
        print(f"下载Cookie文件时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"下载Cookie文件失败: {str(e)}",
            "data": None
        }), 500


# 包装函数：在线程中运行异步函数
