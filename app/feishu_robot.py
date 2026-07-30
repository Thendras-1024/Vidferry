"""Feishu long-connection adapter for the existing Vidferry Agent."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from pathlib import Path
from threading import Semaphore, Thread

from app.feishu_presenter import result_card, tool_sections
from app.project_butler import butler_result, card_action_result


logger = logging.getLogger("vidferry.backend")
MAX_REPLY_CHARS = 3000
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


def _value(source, name, default=""):
    return getattr(source, name, default) if source is not None else default


def feishu_session_id(open_id):
    digest = hashlib.sha256(str(open_id).encode("utf-8")).hexdigest()[:32]
    return f"feishu-{digest}"


def split_reply(text, limit=MAX_REPLY_CHARS):
    text = str(text or "").strip() or "我暂时没有查到结果。"
    return [text[index:index + limit] for index in range(0, len(text), limit)]


def image_paths(value, roots):
    roots = [Path(root).resolve() for root in roots]
    paths = []

    def visit(item):
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            path = Path(item)
            if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                resolved = path.resolve()
                if any(resolved.is_relative_to(root) for root in roots):
                    paths.append(resolved)

    visit(value)
    return list(dict.fromkeys(paths))


def event_text(event):
    message = _value(event, "message")
    if _value(message, "message_type") != "text":
        return ""
    try:
        return str(json.loads(_value(message, "content", "{}") or "{}").get("text") or "").strip()
    except (TypeError, ValueError, json.JSONDecodeError):
        return ""


class FeishuRobot:
    def __init__(self, allowed_open_ids, run_agent, reply, reply_card, send_image=None, image_roots=(), sanitize=str, submit=None):
        self.allowed_open_ids = set(allowed_open_ids)
        self.run_agent = run_agent
        self.reply = reply
        self.reply_card = reply_card
        self.send_image = send_image
        self.image_roots = tuple(image_roots)
        self.sanitize = sanitize
        self.submit = submit or self._submit
        self._inflight = Semaphore(2)

    @staticmethod
    def _submit(task):
        Thread(target=task, name="feishu-agent", daemon=True).start()

    def handle(self, data):
        event = _value(data, "event")
        message = _value(event, "message")
        sender = _value(event, "sender")
        sender_id = _value(sender, "sender_id")
        open_id = str(_value(sender_id, "open_id") or "")
        message_id = str(_value(message, "message_id") or "")

        if _value(message, "chat_type") != "p2p" or _value(sender, "sender_type", "user") != "user":
            return
        if not message_id or not open_id:
            logger.warning("Ignoring Feishu message without message_id or sender")
            return
        if open_id not in self.allowed_open_ids:
            logger.warning("Rejected Feishu user open_id=%s", open_id)
            self.reply(message_id, "当前飞书账号未获授权使用该机器人。")
            return

        text = event_text(event)
        if not text:
            self.reply(message_id, "请发送文本消息。")
            return
        if not self._inflight.acquire(blocking=False):
            self.reply(message_id, "当前请求较多，请稍后再试。")
            return

        request_id = uuid.uuid4().hex[:12]
        try:
            self.reply(message_id, "已收到，正在处理。")
            self.submit(lambda: self._process_and_release(message_id, open_id, text, request_id))
        except Exception:
            self._inflight.release()
            raise

    def _process_and_release(self, message_id, open_id, text, request_id):
        try:
            self._process(message_id, open_id, text, request_id)
        finally:
            self._inflight.release()

    def _process(self, message_id, open_id, text, request_id):
        session_id = feishu_session_id(open_id)
        logger.info(
            "Feishu Agent prompt request_id=%s session_id=%s text=%s",
            request_id,
            session_id,
            self.sanitize(text)[:2000],
        )
        try:
            result = butler_result(text)
            if result is None:
                result = self.run_agent(
                    text,
                    session_id=session_id,
                    context={"source": "feishu", "requestId": request_id},
                )
            tools = tool_sections(result.get("toolResults"), self.sanitize)
            answer = self.sanitize(result.get("answer"))[:4000]
            self.reply_card(message_id, result_card(answer, result.get("toolResults"), self.sanitize))
            if self.send_image:
                for path in image_paths(result.get("toolResults"), self.image_roots):
                    self.send_image(message_id, path)
            logger.info(
                "Feishu Agent reply request_id=%s session_id=%s answer=%s tools=%s",
                request_id,
                session_id,
                answer,
                ", ".join(section["title"] for section in tools) or "none",
            )
        except Exception:
            logger.exception("Feishu Agent request failed request_id=%s", request_id)
            self.reply(message_id, f"处理失败，请稍后重试。请求 ID: {request_id}")

    def handle_card_action(self, data):
        event = _value(data, "event")
        operator = _value(event, "operator")
        open_id = str(_value(operator, "open_id") or "")
        action = _value(_value(event, "action"), "value", {}) or {}
        if open_id not in self.allowed_open_ids:
            return {"toast": {"type": "error", "content": "当前账号未获授权。"}}
        result = card_action_result(action.get("butlerAction"))
        if result is None:
            return {"toast": {"type": "warning", "content": "该操作不可用。"}}
        return {"card": result_card(result["answer"], result["toolResults"], self.sanitize)}


def run_feishu_robot(app_id, app_secret, allowed_open_ids, run_agent, image_roots=(), sanitize=str):
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID and FEISHU_APP_SECRET must be configured.")

    import lark_oapi as lark
    from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
    from lark_oapi.api.im.v1.model.create_image_request import CreateImageRequest
    from lark_oapi.api.im.v1.model.create_image_request_body import CreateImageRequestBody

    client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    def reply(message_id, text):
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .msg_type("text")
                .build()
            )
            .build()
        )
        response = client.im.v1.message.reply(request)
        if not response.success():
            raise RuntimeError(f"Feishu reply failed: code={response.code}, log_id={response.get_log_id()}")

    def reply_card(message_id, card):
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps(card, ensure_ascii=False))
                .msg_type("interactive")
                .build()
            )
            .build()
        )
        response = client.im.v1.message.reply(request)
        if not response.success():
            raise RuntimeError(f"Feishu card reply failed: code={response.code}, log_id={response.get_log_id()}")

    def send_image(message_id, path):
        with Path(path).open("rb") as image:
            upload = (
                CreateImageRequest.builder()
                .request_body(CreateImageRequestBody.builder().image_type("message").image(image).build())
                .build()
            )
            response = client.im.v1.image.create(upload)
        if not response.success() or not response.data or not response.data.image_key:
            raise RuntimeError(f"Feishu image upload failed: code={response.code}, log_id={response.get_log_id()}")
        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"image_key": response.data.image_key}))
                .msg_type("image")
                .build()
            )
            .build()
        )
        response = client.im.v1.message.reply(request)
        if not response.success():
            raise RuntimeError(f"Feishu image reply failed: code={response.code}, log_id={response.get_log_id()}")

    robot = FeishuRobot(allowed_open_ids, run_agent, reply, reply_card, send_image, image_roots, sanitize)

    def card_action(data):
        payload = robot.handle_card_action(data)
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
        return P2CardActionTriggerResponse(payload)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(robot.handle)
        .register_p2_card_action_trigger(card_action)
        .build()
    )
    if not allowed_open_ids:
        logger.warning("No allowed Feishu users configured; all incoming messages will be rejected.")
    logger.info("Starting Feishu robot with %d allowed user(s)", len(allowed_open_ids))
    lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.WARNING).start()


def env_settings():
    app_id = os.getenv("FEISHU_APP_ID") or os.getenv("appID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET") or os.getenv("App_Secret", "")
    allowed = {
        value.strip()
        for value in os.getenv("FEISHU_ALLOWED_OPEN_IDS", "").split(",")
        if value.strip()
    }
    return app_id.strip(), app_secret.strip(), allowed
