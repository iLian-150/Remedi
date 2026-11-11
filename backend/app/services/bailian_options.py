"""模型请求选项；纯函数，不读取凭证或访问网络。"""


def is_kimi_k3(model: str) -> bool:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name == "kimi-k3" or name.startswith("kimi-k3-")


def is_glm53_flash(model: str) -> bool:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name in {"glm-5.3-flash", "glm-5.3-flashx"}


def preserves_reasoning_content(model: str) -> bool:
    return is_kimi_k3(model) or is_glm53_flash(model)


def bailian_request_options(model: str, temperature: float, *, streaming: bool = False) -> dict:
    """按模型协议选择思考、采样与流式工具调用参数。

    Kimi 文档规定 K3 不可关闭思考；Moonshot 参数文档规定其温度固定
    为 1.0，并建议省略。GLM-5.3-Flash 强制思考，工具流式请求需开启 tool_stream。
    其他模型保持原有非思考模式及各教学任务的温度。
    """
    if is_kimi_k3(model):
        return {"enable_thinking": True, "preserve_thinking": True}
    if is_glm53_flash(model):
        options = {
            "thinking": {"type": "enabled", "clear_thinking": False},
            "reasoning_effort": "max",
        }
        if streaming:
            options["tool_stream"] = True
        return options
    return {"enable_thinking": False, "temperature": temperature}
