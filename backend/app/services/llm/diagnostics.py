"""Allowlisted model failure diagnostics; never serialize provider text or URLs."""
import json
from pathlib import Path
import traceback

import httpx
from pydantic import ValidationError

from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.llm.provider import LLMOutputTruncatedError

AGENTS = frozenset({"resume_parser", "jd_analyst", "jd_review_card", "jd_review_doc", "gap_analysis",
    "strategy", "rewrite", "resume_rewrite", "critic", "interview_prep", "partial_rewrite", "materials", "mock_interview"})
STAGES = AGENTS | {"queued", "analyze_jd", "review_cards", "parse_resume", "review", "finalize", "completed"}
ERROR_TYPES = {"StructuredLLMError", "HTTPStatusError", "ConnectError", "ReadTimeout", "ConnectTimeout",
    "PoolTimeout", "WriteTimeout", "ReadError", "WriteError", "RemoteProtocolError", "ValidationError",
    "JSONDecodeError", "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError", "RuntimeError", "LLMOutputTruncatedError"}
MESSAGES = {
    "model_not_found": "配置的模型不存在，或当前账号 / 地区无权使用该模型。",
    "endpoint_not_found": "模型接口返回 404，请检查服务地址和模型名称。",
    "authentication_failed": "模型服务拒绝凭据，请检查密钥。",
    "access_denied": "模型服务拒绝访问，请检查账号权限和服务地区。",
    "quota_exceeded": "模型额度或余额不足。",
    "rate_limited": "模型请求受到限流，请稍后重试。",
    "timeout": "模型请求超时。",
    "connection_error": "无法连接模型服务，请检查网络。",
    "invalid_output": "模型输出无法通过 JSON 或结构校验。",
    "output_truncated": "模型输出达到长度限制，内容未生成完整。",
    "invalid_request": "模型服务拒绝请求参数。",
    "provider_error": "模型服务暂时异常。",
    "generation_failed": "生成失败，未获得有效评测指标。",
}


def safe_failure(exc, pipeline_stage="unknown"):
    chain, seen, current = [], set(), exc
    while current is not None and id(current) not in seen:
        seen.add(id(current)); chain.append(current)
        current = current.__cause__  # Do not infer a reason from an unrelated handled exception.
    stage = next((item.agent_name for item in chain if isinstance(item, StructuredLLMError) and item.agent_name in AGENTS), "unknown")
    if stage == "unknown" and pipeline_stage in STAGES:
        stage = pipeline_stage
    code, status = "generation_failed", None
    for item in reversed(chain):
        if isinstance(item, httpx.HTTPStatusError):
            status = item.response.status_code
            try:
                body = item.response.json()
            except (ValueError, UnicodeError):
                body = {}
            error = body.get("error", {}) if isinstance(body, dict) else {}
            provider_code = error.get("code") if isinstance(error, dict) else None
            if provider_code in ("model_not_found", "ModelNotFound", "ModelNotExist"):
                code = "model_not_found"
            elif provider_code in ("insufficient_quota", "quota_exceeded", "Arrearage", "InsufficientBalance") or status == 402:
                code = "quota_exceeded"
            else:
                code = {400:"invalid_request", 401:"authentication_failed", 403:"access_denied", 404:"endpoint_not_found",
                        408:"timeout", 422:"invalid_request", 429:"rate_limited", 504:"timeout"}.get(status, "provider_error")
            break
        if isinstance(item, httpx.TimeoutException):
            code = "timeout"; break
        if isinstance(item, httpx.TransportError):
            code = "connection_error"; break
        if isinstance(item, LLMOutputTruncatedError):
            code = "output_truncated"; break
        if isinstance(item, (ValidationError, json.JSONDecodeError, ValueError)):
            code = "invalid_output"; break
    root = chain[-1]
    kind = type(root).__name__
    location = None
    app_root = Path(__file__).resolve().parents[2]
    for frame, line_number in traceback.walk_tb(root.__traceback__):
        try:
            file = Path(frame.f_code.co_filename).resolve().relative_to(app_root)
        except ValueError:
            continue
        location = {"file":str(file), "function":frame.f_code.co_name, "line":line_number}
    return {"code":code, "stage":stage, "http_status":status, "message":MESSAGES[code],
            "error_type":kind if kind in ERROR_TYPES else "Exception", "location":location}
