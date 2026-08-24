from flask import g


def _safe_account_name(value):
    return re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", str(value or "").strip()).strip("_") or uuid.uuid4().hex


def _bilibili_account_file(user_name, owner_user_id):
    return _safe_cookie_path(
        f"bilibili_{_safe_account_name(user_name)}.json",
        owner_user_id=owner_user_id,
    )


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


def _read_bilibili_pty_output(process, output_queue):
    while True:
        try:
            output_queue.put(("chunk", process.read(4096)))
        except Exception:
            output_queue.put(("closed", ""))
            return


def _save_bilibili_login_account(user_name, account_file, status_queue, account_id=None, owner_user_id=None):
    relative_cookie_file = Path(account_file).name
    with _db_connect() as conn:
        cursor = conn.cursor()
        if account_id is not None:
            cursor.execute(
                "SELECT type FROM user_info WHERE id = %s AND owner_user_id = %s",
                (account_id, owner_user_id),
            )
            row = cursor.fetchone()
            if row is None or int(row[0]) != 5:
                status_queue.put("500")
                return False
            cursor.execute(
                '''
                UPDATE user_info
                SET type = %s, filePath = %s, userName = %s, status = %s
                WHERE id = %s AND owner_user_id = %s
                ''',
                (5, relative_cookie_file, user_name, 1, account_id, owner_user_id),
            )
        else:
            cursor.execute(
                '''
                INSERT INTO user_info (type, filePath, userName, status, owner_user_id)
                VALUES (%s, %s, %s, %s, %s)
                ''',
                (5, relative_cookie_file, user_name, 1, owner_user_id),
            )
        conn.commit()
    return True


def bilibili_cookie_gen(user_name, status_queue, account_id=None, owner_user_id=None):
    if ensure_biliup_binary is None:
        _emit_sse_error(status_queue, "后端未加载 B 站 biliup 运行时，请检查依赖。")
        return

    account_file = _bilibili_account_file(user_name, owner_user_id)
    account_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        biliup_binary = ensure_biliup_binary(force_check=False)
    except Exception as exc:
        print(f"B站登录准备 biliup 失败 : error_type = {type(exc).__name__}")
        _emit_sse_error(status_queue, f"B站登录准备 biliup 失败: {exc}")
        return

    try:
        from winpty import PtyProcess
    except ImportError:
        _emit_sse_error(status_queue, "B站扫码登录需要 pywinpty 支持，请先执行: python -m pip install pywinpty")
        return

    command = [str(biliup_binary), "-u", str(account_file), "login"]
    backend_logger.info("B站扫码登录开始 account_id=%s", account_id or "new")
    qrcode_path = Path(BASE_DIR / "qrcode.png")
    try:
        initial_qrcode_mtime = qrcode_path.stat().st_mtime_ns
    except OSError:
        initial_qrcode_mtime = None
    sent_qrcode = False
    started_at = time.time()
    output_buffer = ""
    process = None
    try:
        process = PtyProcess.spawn(command, cwd=str(BASE_DIR), dimensions=(42, 160))
        output_queue = Queue()
        threading.Thread(
            target=_read_bilibili_pty_output,
            args=(process, output_queue),
            daemon=True,
        ).start()
        selected_scan_login = False
        reader_closed = False
        while True:
            chunks = []
            while True:
                try:
                    event, payload = output_queue.get_nowait()
                except Empty:
                    break
                if event == "closed":
                    reader_closed = True
                elif payload:
                    chunks.append(payload)

            if chunks:
                output_buffer = (output_buffer + "".join(chunks))[-30000:]
                plain_output = _strip_ansi(output_buffer)
                if not selected_scan_login and "选择一种登录方式" in plain_output and "扫码登录" in plain_output:
                    process.write("\x1b[B\r")
                    selected_scan_login = True

            if not sent_qrcode:
                qrcode_data_url = _terminal_qrcode_to_data_url(output_buffer)
                if not qrcode_data_url:
                    try:
                        current_qrcode_mtime = qrcode_path.stat().st_mtime_ns
                        if current_qrcode_mtime != initial_qrcode_mtime:
                            qrcode_data_url = _image_file_to_data_url(qrcode_path)
                    except OSError:
                        pass
                if qrcode_data_url:
                    status_queue.put(qrcode_data_url)
                    sent_qrcode = True
                    backend_logger.info("B站扫码登录二维码已生成 account_id=%s", account_id or "new")

            if not process.isalive() and reader_closed:
                break

            if time.time() - started_at > 180:
                process.terminate(force=True)
                _emit_sse_error(status_queue, "等待 B 站扫码确认超时，请重新获取二维码。")
                return

            time.sleep(0.2)

        exit_status = process.exitstatus
        if exit_status == 0 and account_file.is_file():
            if _save_bilibili_login_account(user_name, account_file, status_queue, account_id, owner_user_id):
                status_queue.put("200")
                backend_logger.info("B站扫码登录成功 account_id=%s", account_id or "new")
            else:
                _emit_sse_error(status_queue, "B站登录成功但保存账号失败，请检查账号记录。")
        else:
            plain_output = _strip_ansi(output_buffer)
            tail = "\n".join([line.strip() for line in plain_output.splitlines() if line.strip()][-8:])
            backend_logger.error("B站扫码登录失败 account_id=%s exit_status=%s", account_id or "new", exit_status)
            _emit_sse_error(status_queue, tail or f"B站登录失败，biliup 退出码: {exit_status}")
    except Exception as exc:
        backend_logger.exception("B站扫码登录异常 account_id=%s", account_id or "new")
        _emit_sse_error(status_queue, f"B站登录流程异常: {exc}")
    finally:
        if process is not None:
            try:
                if process.isalive():
                    process.terminate(force=True)
            except Exception:
                pass


# SSE 登录接口
@app.route('/login')
def login():
    # 1 小红书 2 视频号 3 抖音 4 快手 5 B站
    type = request.args.get('type')
    # 账号名
    id = (request.args.get('id') or '').strip()
    account_id = request.args.get('accountId')
    account_id = int(account_id) if account_id and account_id.isdigit() else None
    owner_user_id = int(g.current_user["id"])

    if type not in {'1', '2', '3', '4', '5'} or not id:
        return Response("data: 500\n\n", mimetype='text/event-stream')

    if account_id is not None:
        try:
            with _db_connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT type FROM user_info WHERE id = %s AND owner_user_id = %s", (account_id, owner_user_id))
                row = cursor.fetchone()
                if row is None or str(row[0]) != str(type):
                    return Response("data: 500\n\n", mimetype='text/event-stream')
        except Exception as e:
            print(f"校验重新连接账号失败 : error_type = {e.__class__.__name__}")
            return Response("data: 500\n\n", mimetype='text/event-stream')

    # 模拟一个用于异步通信的队列
    status_queue = Queue()
    queue_key = f"{type}:{account_id or id}"
    active_queues[queue_key] = status_queue
    # 启动异步任务线程
    thread = threading.Thread(target=run_async_function, args=(type,id,status_queue,account_id,owner_user_id), daemon=True)
    thread.start()
    response = Response(sse_stream(status_queue, queue_key), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # 关键：禁用 Nginx 缓冲
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Connection'] = 'keep-alive'
    return response

