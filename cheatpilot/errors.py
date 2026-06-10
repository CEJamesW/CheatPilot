from __future__ import annotations


def is_llm_rate_limit_error(exc: Exception) -> bool:
    message = str(exc)
    return (
        "LLM tool-use request failed" in message
        and ("HTTP Error 429" in message or "Too Many Requests" in message)
    )


def is_llm_malformed_response_error(exc: Exception) -> bool:
    message = str(exc)
    return "LLM 返回格式无效" in message or "LLM 返回不是合法 JSON" in message


def user_facing_error(exc: Exception) -> str:
    message = str(exc)
    if is_llm_malformed_response_error(exc):
        return (
            f"LLM 响应格式异常：{message}。"
            "请确认当前模型/中转服务支持 OpenAI-compatible Chat Completions，并能返回 choices[0].message。"
        )
    if "LLM tool-use request failed" in message:
        if is_llm_rate_limit_error(exc):
            return (
                f"LLM 请求被服务端限流：{message}。"
                "程序已按配置自动重试；这次没有执行本地规则兜底。请稍后再发，或更换/升级可用的 LLM 额度。"
            )
        return (
            f"LLM 请求失败：{message}。"
            "这次没有执行本地规则兜底；请稍后重试。"
        )
    if "CHEATPILOT_LLM_BASE_URL and CHEATPILOT_LLM_API_KEY are required" in message:
        return "LLM 配置缺失：请在 .env 里设置 CHEATPILOT_LLM_BASE_URL 和 CHEATPILOT_LLM_API_KEY。"
    return f"执行失败：{message}"
