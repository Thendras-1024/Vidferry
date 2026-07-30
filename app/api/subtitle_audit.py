"""管理员字幕审查本地接口。"""


@app.route('/admin/subtitle-audits', methods=['GET'])
def list_subtitle_audits_route():
    try:
        data = list_subtitle_audits(
            keyword=request.args.get('keyword', ''),
            status=request.args.get('status', ''),
            sort=request.args.get('sort', 'saved_desc'),
            page=request.args.get('page', 1),
            page_size=request.args.get('pageSize', 20),
        )
        return _json_response(200, 'success', data)
    except Exception as exc:
        backend_logger.exception("字幕审查列表读取失败")
        return _json_response(500, f"字幕审查列表读取失败 : {str(exc)}", None, 500)


@app.route('/admin/subtitle-audits', methods=['DELETE'])
def delete_subtitle_audits_route():
    payload = request.get_json(silent=True) or {}
    job_ids = payload.get('jobIds')
    if not isinstance(job_ids, list):
        return _json_response(400, 'jobIds 必须为数组', None, 400)
    try:
        data = delete_subtitle_audits(job_ids)
        backend_logger.info("字幕审查快照删除完成 : requestedCount = %s | deletedCount = %s", len(job_ids), data['deletedCount'])
        return _json_response(200, '字幕审查记录已删除', data)
    except ValueError as exc:
        return _json_response(400, str(exc), None, 400)
    except Exception as exc:
        backend_logger.exception("字幕审查快照删除失败 : requestedCount = %s", len(job_ids))
        return _json_response(500, f"字幕审查快照删除失败 : {str(exc)}", None, 500)


@app.route('/admin/subtitle-audits/<job_id>', methods=['GET'])
def get_subtitle_audit_detail_route(job_id):
    try:
        data = get_subtitle_audit_detail(job_id)
        if not data:
            return _json_response(404, '该任务生成时尚未启用审查记录', None, 404)
        return _json_response(200, 'success', data)
    except Exception as exc:
        backend_logger.exception("字幕审查详情读取失败 : jobId = %s", job_id)
        return _json_response(500, f"字幕审查详情读取失败 : {str(exc)}", None, 500)
