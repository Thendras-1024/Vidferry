"""Vidferry 自定义异常与对外错误码的唯一真相源。

像 ``llm_prompts`` 集中提示词一样，本模块集中所有业务异常类定义，
以及与 LLM 异常强绑定的 ``category`` 到错误码/文案的映射。各模块应从本文件引用异常类；
为兼容历史 import，原定义模块(llm_harness/backend_common/agent_orchestrator/prepublish_guard)
保留 re-export，现有 import/catch 一行不用改。

本模块只依赖标准库，不 import 任何 app 模块，避免循环依赖。
"""


# --------------------------------------------------------------------------- #
# LLM 异常
# --------------------------------------------------------------------------- #

class LLMContractError(RuntimeError):
    """模型输出可解析但未满足结构化契约(字段缺失/值非法/JSON 损坏/空 content)。

    category 用于细分失败原因，供 error_catalog 输出可定位的错误码与建议。
    """

    def __init__(self, contract_id, violations, raw_text="", category="contract_validation"):
        self.contract_id = contract_id
        self.category = category
        self.violations = [str(item) for item in violations if str(item)] or ["模型输出不符合契约"]
        self.raw_text = str(raw_text or "")
        self.detail = "；".join(self.violations[:8])
        super().__init__(f"模型输出不符合 {contract_id} 契约[{category}]：{self.detail}")


class LLMRequestError(RuntimeError):
    """LLM 网络/HTTP/响应层错误，携带稳定分类码(category)便于定位与展示。"""

    def __init__(self, category, detail, *, http_code=None, model="", finish_reason=None, recommendation=""):
        self.category = category
        self.http_code = http_code
        self.model = str(model or "")
        self.finish_reason = finish_reason
        self.recommendation = str(recommendation or "")
        self.detail = str(detail or "")
        parts = [f"[{category}] {self.detail}"]
        if model:
            parts.append(f"model={model}")
        if http_code:
            parts.append(f"http={http_code}")
        if finish_reason:
            parts.append(f"finish_reason={finish_reason}")
        if recommendation:
            parts.append(f"建议:{recommendation}")
        super().__init__(" | ".join(parts))


# LLM 异常 category → (对外错误码, 错误类型, 面向用户的中文建议)。
# 与 LLM 异常类放在一起，方便新增 category 时同步维护错误码与文案。
LLM_CATEGORY_ERROR_INFO = {
    "empty_content": ("VF-LLM-EMPTY-RESPONSE", "LLM_EMPTY_RESPONSE", "模型返回为空，常见于思考模型推理占用全部 token；建议调大 max_tokens 或更换模型设置。"),
    "length_truncated": ("VF-LLM-EMPTY-RESPONSE", "LLM_EMPTY_RESPONSE", "模型输出被 max_tokens 截断；建议调大 max_tokens 或关闭推理减少 token 占用。"),
    "content_filtered": ("VF-LLM-CONTENT-FILTERED", "LLM_CONTENT_FILTERED", "模型输出触发内容安全审查，请调整输入内容或更换模型。"),
    "json_parse": ("VF-LLM-JSON-INVALID", "LLM_JSON_INVALID", "模型返回的 JSON 无法解析(可能被截断或格式错误)；建议调大 max_tokens 或重试。"),
    "contract_validation": ("VF-LLM-CONTRACT-INVALID", "LLM_CONTRACT_ERROR", "模型输出未满足中文与结构化约束，系统已尝试修正但仍未通过。"),
    "network_timeout": ("VF-LLM-TIMEOUT", "LLM_TIMEOUT", "模型请求超时；可调大 LLM_TIMEOUT，或关闭推理降低延迟。"),
    "network_connection": ("VF-LLM-UNREACHABLE", "LLM_UNREACHABLE", "无法连接模型服务；请检查网络、代理与所选模型 Base URL 是否可达。"),
    "http_auth": ("VF-LLM-AUTH", "LLM_AUTH_ERROR", "模型鉴权失败；请检查所选模型的 API Key 是否有效及是否有该模型权限。"),
    "http_not_found": ("VF-LLM-MODEL-NOT-FOUND", "LLM_MODEL_NOT_FOUND", "模型或接口不存在；请检查所选模型名称与 Base URL 是否匹配。"),
    "http_rate_limit": ("VF-LLM-RATE-LIMIT", "LLM_RATE_LIMIT", "触发模型限流或额度不足；请稍后重试或提升配额。"),
    "input_content_filtered": ("VF-LLM-INPUT-CONTENT-FILTERED", "LLM_INPUT_CONTENT_FILTERED", "输入图片或文本触发内容审核；请检查对应高光候选的关键帧，改用邻近画面或跳过该候选。"),
    "http_bad_request": ("VF-LLM-BAD-REQUEST", "LLM_BAD_REQUEST", "请求参数被模型拒绝；多为模型不支持 response_format，请核对兼容性。"),
    "http_server_error": ("VF-LLM-PROVIDER-ERROR", "LLM_PROVIDER_ERROR", "模型服务商侧异常；请稍后重试。"),
    "http_other": ("VF-LLM-HTTP-ERROR", "LLM_HTTP_ERROR", "模型接口返回异常 HTTP 状态；请查看后端日志中的 http 状态码与响应。"),
}


# --------------------------------------------------------------------------- #
# 工作流 / 业务异常
# --------------------------------------------------------------------------- #

class WorkflowConflictError(ValueError):
    """工作流冲突(任务占用、状态非法等)，带稳定错误码与可选上下文数据。

    继承 ValueError 以兼容既有 ``isinstance`` 判断。
    """

    def __init__(self, message, error_code, error_type="WORKFLOW_CONFLICT", data=None):
        super().__init__(message)
        self.error_code = error_code
        self.error_type = error_type
        self.data = data or {}


class BackgroundQueueFullError(RuntimeError):
    """后台资源的全局或 owner 队列准入已满。"""

    def __init__(self, resource, scope="global"):
        self.resource = str(resource or "unknown")
        self.scope = str(scope or "global")
        self.error_code = (
            f"VF-{self.scope.upper()}-{self.resource.upper()}-QUEUE-FULL"
        )
        super().__init__("任务队列已满，请稍后重试")


class NoSpeechDetectedError(RuntimeError):
    """ASR 未识别到可用人声，字幕处理应跳过而非失败。"""
    pass


# --------------------------------------------------------------------------- #
# Agent 异常
# --------------------------------------------------------------------------- #

class AgentSessionLeaseLostError(RuntimeError):
    """Agent 会话租约失效(被其他请求抢占或超时)，需要用户重试。"""
    pass


class AgentGuardError(RuntimeError):
    """发布前质检拦截/需人工确认，带错误码、HTTP 状态与质检结果。"""

    def __init__(self, message, error_code, status_code, result=None):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.result = result or {}
