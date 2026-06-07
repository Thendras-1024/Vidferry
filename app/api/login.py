def _safe_account_name(value):
    return re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("_") or uuid.uuid4().hex


def _bilibili_account_file(user_name):
    return Path(BASE_DIR / "cookiesFile" / f"bilibili_{_safe_account_name(user_name)}.json")


def _image_file_to_data_url(path):
    image_path = Path(path)
    suffix = image_path.suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode('ascii')}"


def _emit_sse_error(status_queue, message):
    if message:
        status_queue.put(f"ERROR::{str(message).strip()}")
    status_queue.put("500")


def _strip_ansi(value):
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>]", "", str(value or ""))


def _terminal_qrcode_to_data_url(output):
    lines = []
    for raw_line in _strip_ansi(output).splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        qr_chars = sum(1 for char in line if char in {"█", "▀", "▄", " "})
        if qr_chars >= 20 and qr_chars >= len(line) * 0.75:
            lines.append(line)

    if len(lines) < 8:
        return ""

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return ""

    cell = 6
    margin = 18
    width = max(len(line) for line in lines) * cell
    height = len(lines) * cell * 2
    image = Image.new("RGB", (width + margin * 2, height + margin * 2), "white")
    draw = ImageDraw.Draw(image)

    for row, line in enumerate(lines):
        for col, char in enumerate(line.ljust(width // cell)):
            x = margin + col * cell
            y = margin + row * cell * 2
            if char == "█":
                draw.rectangle([x, y, x + cell - 1, y + cell * 2 - 1], fill="black")
            elif char == "▀":
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill="black")
            elif char == "▄":
                draw.rectangle([x, y + cell, x + cell - 1, y + cell * 2 - 1], fill="black")

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"


def _save_bilibili_login_account(user_name, account_file, status_queue, account_id=None):
    relative_cookie_file = Path(account_file).name
    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        if account_id is not None:
            cursor.execute("SELECT type FROM user_info WHERE id = ?", (account_id,))
            row = cursor.fetchone()
            if row is None or int(row[0]) != 5:
                status_queue.put("500")
                return False
            cursor.execute(
                '''
                UPDATE user_info
                SET type = ?, filePath = ?, userName = ?, status = ?
                WHERE id = ?
                ''',
                (5, relative_cookie_file, user_name, 1, account_id),
            )
        else:
            cursor.execute(
                '''
                INSERT INTO user_info (type, filePath, userName, status)
                VALUES (?, ?, ?, ?)
                ''',
                (5, relative_cookie_file, user_name, 1),
            )
        conn.commit()
    return True


# B站登录已迁移至 myUtils/login.py，使用 Playwright 弹窗模式。


# SSE 登录接口
@app.route('/login')
def login():
    # 1 小红书 2 视频号 3 抖音 4 快手 5 B站
    type = request.args.get('type')
    # 账号名
    id = (request.args.get('id') or '').strip()
    account_id = request.args.get('accountId')
    account_id = int(account_id) if account_id and account_id.isdigit() else None

    if type not in {'1', '2', '3', '4', '5'} or not id:
        return Response("data: 500\n\n", mimetype='text/event-stream')

    if account_id is not None:
        try:
            with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT type FROM user_info WHERE id = ?", (account_id,))
                row = cursor.fetchone()
                if row is None or str(row[0]) != str(type):
                    return Response("data: 500\n\n", mimetype='text/event-stream')
        except Exception as e:
            print(f"校验重新连接账号失败: {e}")
            return Response("data: 500\n\n", mimetype='text/event-stream')

    # 模拟一个用于异步通信的队列
    status_queue = Queue()
    queue_key = f"{type}:{account_id or id}"
    active_queues[queue_key] = status_queue
    # 启动异步任务线程
    thread = threading.Thread(target=run_async_function, args=(type,id,status_queue,account_id), daemon=True)
    thread.start()
    response = Response(sse_stream(status_queue, queue_key), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # 关键：禁用 Nginx 缓冲
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Connection'] = 'keep-alive'
    return response

