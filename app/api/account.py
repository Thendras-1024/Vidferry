from flask import g


ACCOUNT_COOKIE_CHECK_COOLDOWN_SECONDS = 60
_account_cookie_check_last_at = {}
ACCOUNT_COOKIE_CHECK_SUCCESS_COOLDOWN_SECONDS = 600
ACCOUNT_COOKIE_CHECK_FAILURE_COOLDOWN_SECONDS = 120
ACCOUNT_COOKIE_CHECK_ERROR_COOLDOWN_SECONDS = 60
ACCOUNT_COOKIE_CHECK_COOLDOWN_SECONDS = ACCOUNT_COOKIE_CHECK_SUCCESS_COOLDOWN_SECONDS
_account_cookie_check_state = {}


def _current_account_owner_id():
    user = getattr(g, "current_user", None)
    if not user or not user.get("id"):
        raise PermissionError("登录用户不能为空")
    return int(user["id"])


def _owned_account(cursor, account_id, owner_user_id):
    cursor.execute("SELECT * FROM user_info WHERE id = ? AND owner_user_id = ?", (int(account_id), int(owner_user_id)))
    return cursor.fetchone()


def _account_row_to_list(row):
    return [row["id"], row["type"], row["filePath"], row["userName"], row["status"]]


def _resolve_valid_account_cookie_notifications(results):
    for result in results:
        if result.get("checkStatus") == "valid":
            resolve_publish_cookie_invalid_notifications(result["id"], result["ownerUserId"])


def _account_check_payload(row, *, checked=False, skipped=False, blocked=False, valid=False, check_status="unknown", message="", retry_after_seconds=0, status_override=None):
    status_value = status_override if status_override is not None else row["status"]
    return {
        "id": row["id"],
        "type": row["type"],
        "platform": platform_name(row["type"]),
        "filePath": row["filePath"],
        "name": row["userName"],
        "ownerUserId": row["owner_user_id"],
        "status": int(status_value if status_value is not None else 0),
        "checked": bool(checked),
        "skipped": bool(skipped),
        "blocked": bool(blocked),
        "valid": bool(valid),
        "checkStatus": check_status,
        "message": message,
        "retryAfterSeconds": int(max(0, retry_after_seconds or 0)),
    }


def _run_bilibili_cookie_check_sync(file_path, owner_user_id=None):
    account_file = _safe_cookie_path(file_path, owner_user_id=owner_user_id)
    if not account_file.is_file():
        backend_logger.warning("bilibili cookie check failed : reason = cookie_file_missing")
        return False

    try:
        from uploader.bilibili_uploader.runtime import run_biliup_command
    except Exception as exc:
        backend_logger.warning(
            "bilibili cookie check failed : reason = runtime_load_error error_type = %s",
            type(exc).__name__,
        )
        return False

    backend_logger.info("bilibili cookie check started : action = renew")
    result = run_biliup_command(["-u", str(account_file), "renew"])
    if result.returncode == 0:
        backend_logger.info("bilibili cookie check completed : valid = true return_code = 0")
        return True

    output = "\n".join(
        item.strip()
        for item in [getattr(result, "stderr", ""), getattr(result, "stdout", "")]
        if str(item or "").strip()
    )
    backend_logger.warning(
        "bilibili cookie check failed : reason = renew_failed return_code = %s has_output = %s",
        result.returncode,
        bool(output),
    )
    return False


def _run_cookie_check_sync(platform_type, file_path, owner_user_id=None):
    try:
        platform_type_value = int(platform_type)
    except (TypeError, ValueError):
        platform_type_value = 0

    if platform_type_value == 5:
        return _run_bilibili_cookie_check_sync(file_path, owner_user_id=owner_user_id)

    if check_cookie is None:
        raise RuntimeError("后端未加载 Cookie 检查模块，请检查依赖。")

    file_path = _safe_cookie_filename(file_path)
    if owner_user_id is not None:
        _safe_cookie_path(file_path, owner_user_id=owner_user_id, must_exist=True)
        file_path = f"{int(owner_user_id)}/{file_path}"

    result = {"value": False, "error": None}

    def runner():
        try:
            result["value"] = bool(asyncio.run(check_cookie(platform_type_value, str(file_path))))
        except Exception as exc:
            result["error"] = exc

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        runner()
    else:
        thread = threading.Thread(target=runner)
        thread.start()
        thread.join()

    if result["error"]:
        raise result["error"]
    return bool(result["value"])


def _cookie_check_error_message(platform_type, exc):
    message = getattr(exc, "user_message", "")
    if message:
        return message
    platform = platform_name(platform_type)
    if "timeout" in type(exc).__name__.lower():
        return f"{platform}页面访问超时，请检查网络后重试检测。"
    return f"{platform}登录状态检测异常，请稍后重试。"


def _check_account_cookie_row(cursor, row, *, force=False):
    now = time.time()
    account_id = int(row["id"])
    cached_state = _account_cookie_check_state.get(account_id) or {}
    retry_after_seconds = int(max(0, float(cached_state.get("blocked_until") or 0) - now))
    current_status = int(row["status"] if row["status"] is not None else 0)
    backend_logger.info(
        "account cookie check started : account_id = %s platform_type = %s current_status = %s",
        account_id,
        row["type"],
        current_status,
    )

    if not force and retry_after_seconds > 0:
        backend_logger.info(
            "account cookie check skipped : account_id = %s retry_after_seconds = %s",
            account_id,
            retry_after_seconds,
        )
        return _account_check_payload(
            row,
            skipped=True,
            blocked=True,
            valid=current_status == 1,
            check_status="skipped",
            message=f"为避免短时间频繁访问平台触发风控，请 {retry_after_seconds} 秒后再检测。",
            retry_after_seconds=retry_after_seconds,
        )

    try:
        valid = _run_cookie_check_sync(row["type"], row["filePath"], row["owner_user_id"])
    except Exception as exc:
        backend_logger.exception(
            "account cookie check failed : account_id = %s reason = check_exception error_type = %s",
            account_id,
            type(exc).__name__,
        )
        _account_cookie_check_state[account_id] = {
            "checked_at": now,
            "valid": False,
            "error": str(exc),
            "blocked_until": now + ACCOUNT_COOKIE_CHECK_ERROR_COOLDOWN_SECONDS,
        }
        return _account_check_payload(
            row,
            checked=True,
            valid=current_status == 1,
            check_status="error",
            message=_cookie_check_error_message(row["type"], exc),
            retry_after_seconds=ACCOUNT_COOKIE_CHECK_ERROR_COOLDOWN_SECONDS,
        )

    next_status = 1 if valid else 0
    cursor.execute("UPDATE user_info SET status = ? WHERE id = ?", (next_status, account_id))
    log_method = backend_logger.info if valid else backend_logger.warning
    log_method(
        "account cookie check completed : account_id = %s valid = %s previous_status = %s next_status = %s",
        account_id,
        valid,
        current_status,
        next_status,
    )
    cooldown_seconds = (
        ACCOUNT_COOKIE_CHECK_SUCCESS_COOLDOWN_SECONDS
        if valid
        else ACCOUNT_COOKIE_CHECK_FAILURE_COOLDOWN_SECONDS
    )
    _account_cookie_check_last_at[account_id] = now
    _account_cookie_check_state[account_id] = {
        "checked_at": now,
        "valid": valid,
        "error": None,
        "blocked_until": now + cooldown_seconds,
    }

    return _account_check_payload(
        row,
        checked=True,
        valid=valid,
        check_status="valid" if valid else "invalid",
        message="Cookie 有效" if valid else "Cookie 已过期或不可用",
        retry_after_seconds=cooldown_seconds,
        status_override=next_status,
    )


def _load_accounts(cursor, owner_user_id, account_ids=None):
    if account_ids:
        placeholders = ",".join("?" for _ in account_ids)
        cursor.execute(f"SELECT * FROM user_info WHERE owner_user_id = ? AND id IN ({placeholders})", [owner_user_id, *account_ids])
    else:
        cursor.execute("SELECT * FROM user_info WHERE owner_user_id = ?", (owner_user_id,))
    return cursor.fetchall()


def _list_all_accounts(cursor, owner_user_id):
    cursor.execute("SELECT * FROM user_info WHERE owner_user_id = ?", (owner_user_id,))
    return [_account_row_to_list(row) for row in cursor.fetchall()]


def _check_accounts_for_publish(targets):
    if not targets:
        return []
    owner_user_id = _current_account_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        results = []
        for target in targets:
            account_id = target.get("accountId")
            account_file = str(target.get("accountFile") or "").strip()
            platform_type = int(target.get("platformType") or 0)
            row = None
            if account_id:
                cursor.execute("SELECT * FROM user_info WHERE id = ? AND owner_user_id = ?", (account_id, owner_user_id))
                row = cursor.fetchone()
            if not row and account_file:
                cursor.execute(
                    "SELECT * FROM user_info WHERE type = ? AND filePath = ? AND owner_user_id = ?",
                    (platform_type, account_file, owner_user_id),
                )
                row = cursor.fetchone()
            if not row:
                raise ValueError(f"{platform_name(platform_type)}账号不存在，请重新选择账号。")
            if int(row["status"] if row["status"] is not None else 0) != 1:
                raise ValueError(f"{platform_name(platform_type)}账号“{row['userName']}”当前状态异常，请重新连接后再发布。")
            target.update({
                "accountId": row["id"],
                "accountFile": row["filePath"],
                "accountName": row["userName"],
                "ownerUserId": row["owner_user_id"],
            })
            results.append(_account_check_payload(row, skipped=True, valid=True, message="发布前跳过主动 Cookie 验证。"))
        conn.commit()
        return results


def _check_named_publish_account(platform_type, account_name, owner_user_id=None):
    account_name = str(account_name or "").strip()
    if not account_name:
        return None
    owner_user_id = int(owner_user_id) if owner_user_id is not None else _current_account_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM user_info WHERE type = ? AND userName = ? AND owner_user_id = ?",
            (int(platform_type), account_name, owner_user_id),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"{platform_name(platform_type)}账号“{account_name}”不存在，请重新选择账号。")
        if int(row["status"] if row["status"] is not None else 0) != 1:
            raise ValueError(f"{platform_name(platform_type)}账号“{account_name}”当前状态异常，请重新连接后再发布。")
        return _account_check_payload(row, skipped=True, valid=True, message="发布前跳过主动 Cookie 验证。")


_COOKIE_PLATFORM_DOMAINS = {
    1: ("xiaohongshu.com",),
    2: ("channels.weixin.qq.com", "weixin.qq.com"),
    3: ("douyin.com",),
    4: ("kuaishou.com",),
    5: ("bilibili.com",),
}


def _cookie_platform_candidates(payload):
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    domains = {
        str(item.get("domain") or "").lower().lstrip(".")
        for item in cookies or []
        if isinstance(item, dict)
    }
    candidates = {
        platform_type
        for platform_type, markers in _COOKIE_PLATFORM_DOMAINS.items()
        if any(domain == marker or domain.endswith(f".{marker}") for domain in domains for marker in markers)
    }
    if isinstance(payload, dict):
        serialized_keys = json.dumps(payload, ensure_ascii=True).lower()
        if any(key in serialized_keys for key in ('"sessdata"', '"bili_jct"', '"dedeuserid"', '"cookie_info"')):
            candidates.add(5)
    return sorted(candidates)


def _import_account_name(cursor, platform_type, username):
    prefix = f"{platform_name(platform_type)}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}-{username}"
    candidate = prefix
    suffix = 2
    while cursor.execute("SELECT 1 FROM user_info WHERE userName = ?", (candidate,)).fetchone():
        candidate = f"{prefix}-{suffix}"
        suffix += 1
    return candidate


@app.route("/accounts/import-cookie", methods=["POST"])
def import_cookie_account():
    owner_user_id = _current_account_owner_id()
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify({"code": 400, "msg": "请选择 Cookie JSON 文件", "data": None}), 400
    if Path(uploaded.filename).suffix.lower() != ".json":
        return jsonify({"code": 400, "msg": "Cookie 文件必须是 JSON 格式", "data": None}), 400
    try:
        payload = json.load(uploaded.stream)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({"code": 400, "msg": "Cookie 文件不是有效 JSON", "data": None}), 400
    if not isinstance(payload, dict):
        return jsonify({"code": 400, "msg": "Cookie 文件格式不受支持", "data": None}), 400

    candidates = _cookie_platform_candidates(payload)
    selected = request.form.get("platformType", "").strip()
    try:
        selected_type = int(selected) if selected else 0
    except ValueError:
        selected_type = 0
    if selected_type and selected_type not in {1, 2, 3, 4, 5}:
        return jsonify({"code": 400, "msg": "平台类型不支持", "data": None}), 400
    if not selected_type and len(candidates) != 1:
        return jsonify({
            "code": 409,
            "msg": "无法唯一识别 Cookie 所属平台，请手动选择平台",
            "data": {"candidates": candidates},
        }), 409
    if selected_type and candidates and selected_type not in candidates:
        return jsonify({"code": 400, "msg": "所选平台与 Cookie 内容不匹配", "data": {"candidates": candidates}}), 400
    platform_type = selected_type or candidates[0]
    filename = f"{uuid.uuid4().hex}.json"
    destination = _safe_cookie_path(filename, owner_user_id=owner_user_id)
    temporary = destination.with_name(f".{filename}.uploading.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        valid = _run_cookie_check_sync(platform_type, temporary.name, owner_user_id=owner_user_id)
    except Exception:
        temporary.unlink(missing_ok=True)
        backend_logger.exception("cookie import validation failed : platform_type = %s", platform_type)
        return jsonify({"code": 502, "msg": "Cookie 校验异常，请检查网络和平台状态后重试", "data": None}), 502
    if not valid:
        temporary.unlink(missing_ok=True)
        return jsonify({"code": 400, "msg": "Cookie 已过期或不可用于所选平台", "data": None}), 400

    try:
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            user_name = _import_account_name(cursor, platform_type, str(g.current_user.get("username") or "user"))
            cursor.execute(
                "INSERT INTO user_info (type, filePath, userName, status, owner_user_id) VALUES (?, ?, ?, ?, ?) RETURNING id",
                (platform_type, filename, user_name, 1, owner_user_id),
            )
            account_id = cursor.fetchone()[0]
            temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise
    return jsonify({
        "code": 200,
        "msg": "Cookie 导入成功",
        "data": {"id": account_id, "platformType": platform_type, "name": user_name, "filePath": filename},
    }), 200


@app.route("/getAccounts", methods=['GET'])
def getAccounts():
    """快速获取所有账号信息，不进行cookie验证"""
    try:
        owner_user_id = _current_account_owner_id()
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            rows_list = _list_all_accounts(cursor, owner_user_id)

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
def getValidAccounts():
    owner_user_id = _current_account_owner_id()
    with _db_connect() as conn:
        conn.row_factory = True
        cursor = conn.cursor()
        rows = _load_accounts(cursor, owner_user_id)
        results = [_check_account_cookie_row(cursor, row) for row in rows]
        conn.commit()
        _resolve_valid_account_cookie_notifications(results)
        rows_list = _list_all_accounts(cursor, owner_user_id)
        return jsonify(
                        {
                            "code": 200,
                            "msg": None,
                            "data": rows_list
                        }),200


@app.route("/accounts/check-cookies", methods=["POST"])
def check_account_cookies():
    try:
        owner_user_id = _current_account_owner_id()
        payload = request.get_json(silent=True) or {}
        raw_ids = payload.get("accountIds") or payload.get("ids") or []
        account_ids = [
            int(item)
            for item in raw_ids
            if str(item).isdigit()
        ]
        check_all = bool(payload.get("all")) or not account_ids

        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            rows = _load_accounts(cursor, owner_user_id, None if check_all else account_ids)
            found_ids = {int(row["id"]) for row in rows}
            missing_ids = [item for item in account_ids if item not in found_ids]
            results = [_check_account_cookie_row(cursor, row) for row in rows]
            conn.commit()
            _resolve_valid_account_cookie_notifications(results)
            accounts = _list_all_accounts(cursor, owner_user_id)

        invalid = [item for item in results if item.get("checkStatus") == "invalid"]
        errors = [item for item in results if item.get("checkStatus") == "error"]
        retry_after_seconds = max((int(item.get("retryAfterSeconds") or 0) for item in results), default=0)
        return jsonify({
            "code": 200,
            "msg": None,
            "data": {
                "items": results,
                "accounts": accounts,
                "invalid": invalid,
                "invalidCount": len(invalid),
                "errors": errors,
                "errorCount": len(errors),
                "checkedCount": len([item for item in results if item.get("checked")]),
                "skippedCount": len([item for item in results if item.get("skipped")]),
                "blockedCount": len([item for item in results if item.get("blocked")]),
                "missingIds": missing_ids,
                "cooldownSeconds": retry_after_seconds or ACCOUNT_COOKIE_CHECK_COOLDOWN_SECONDS,
                "retryAfterSeconds": retry_after_seconds,
            }
        }), 200
    except Exception:
        backend_logger.exception("检查账号 Cookie 失败")
        return jsonify({
            "code": 500,
            "msg": "检查账号 Cookie 失败，请稍后重试。",
            "data": None
        }), 500

@app.route('/deleteAccount', methods=['DELETE'])
def delete_account():
    payload = request.get_json(silent=True) or {}
    account_id = payload.get('id') or request.args.get('id')

    if not account_id or not account_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing account ID",
            "data": None
        }), 400

    account_id = int(account_id)

    try:
        owner_user_id = _current_account_owner_id()
        # 获取数据库连接
        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()

            # 查询要删除的记录
            record = _owned_account(cursor, account_id, owner_user_id)

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "account not found",
                    "data": None
                }), 404

            # 删除关联的cookie文件
            if record.get('filePath'):
                try:
                    cookie_file_path = _safe_cookie_path(record['filePath'], owner_user_id=owner_user_id)
                except ValueError as exc:
                    cookie_file_path = None
                    print(f"⚠️ 跳过非法Cookie路径: {record['filePath']} {exc}")
                if cookie_file_path and cookie_file_path.exists():
                    try:
                        cookie_file_path.unlink()
                        print(f"✅ Cookie文件已删除: {cookie_file_path}")
                    except Exception as e:
                        print(f"⚠️ 删除Cookie文件失败: {e}")

            # 删除数据库记录
            cursor.execute("DELETE FROM user_info WHERE id = ? AND owner_user_id = ?", (account_id, owner_user_id))
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
        owner_user_id = _current_account_owner_id()
        data = request.get_json(silent=True) or {}
        platform_type = int(data.get("type") or 0)
        user_name = (data.get("userName") or data.get("name") or "").strip()
        file_path = (data.get("filePath") or "").strip()
        status = int(data.get("status") if data.get("status") is not None else 0)
        if platform_type not in {1, 2, 3, 4, 5}:
            return jsonify({"code": 400, "msg": "不支持的平台类型", "data": None}), 400
        if not user_name:
            return jsonify({"code": 400, "msg": "账号名称不能为空", "data": None}), 400
        if file_path:
            file_path = _safe_cookie_filename(file_path)
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

        with _db_connect() as conn:
            conn.row_factory = True
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO user_info (type, filePath, userName, status, owner_user_id)
                VALUES (?, ?, ?, ?, ?)
                RETURNING id
            ''', (platform_type, file_path, user_name, status, owner_user_id))
            account_id = cursor.fetchone()[0]
            conn.commit()

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
