"""Publish account group API."""


@app.route('/publish/account-groups', methods=['GET'])
def list_publish_account_groups_route():
    try:
        return _json_response(data=list_publish_account_groups())
    except Exception as exc:
        backend_logger.exception("list publish account groups failed")
        return _json_response(500, str(exc), None, 500)


@app.route('/publish/account-groups', methods=['POST'])
def create_publish_account_group_route():
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=create_publish_account_group(payload.get("name"), payload.get("accounts") or []), status=201)
    except WorkflowConflictError as exc:
        return _error_response(409, str(exc), exc.error_code, exc.error_type, exc.data)
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception as exc:
        backend_logger.exception("create publish account group failed")
        return _json_response(500, str(exc), None, 500)


@app.route('/publish/account-groups/<int:group_id>', methods=['PATCH'])
def update_publish_account_group_route(group_id):
    try:
        payload = request.get_json(silent=True) or {}
        return _json_response(data=update_publish_account_group(group_id, payload.get("name"), payload.get("accounts") or []))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except WorkflowConflictError as exc:
        return _error_response(409, str(exc), exc.error_code, exc.error_type, exc.data)
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception as exc:
        backend_logger.exception("update publish account group failed : group_id=%s", group_id)
        return _json_response(500, str(exc), None, 500)


@app.route('/publish/account-groups/<int:group_id>', methods=['DELETE'])
def delete_publish_account_group_route(group_id):
    try:
        return _json_response(data=delete_publish_account_group(group_id))
    except LookupError as exc:
        return _json_response(404, str(exc), None, 404)
    except Exception as exc:
        backend_logger.exception("delete publish account group failed : group_id=%s", group_id)
        return _json_response(500, str(exc), None, 500)
