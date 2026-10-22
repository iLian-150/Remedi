"""百炼各请求模型的选项；纯函数，不读取凭证或访问网络。"""


def is_kimi_k3(model: str) -> bool:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name == "kimi-k3" or name.startswith("kimi-k3-")


def bailian_request_options(model: str, temperature: float) -> dict:
    """K3 保留式思考始终开启，省略固定采样参数以使用服务端默认值。

    百炼 Kimi 文档规定 K3 不可关闭思考；Moonshot 参数文档规定其温度固定
    为 1.0，并建议省略。Qwen 保持原有非思考模式及各教学任务的温度。
    """
    if is_kimi_k3(model):
        return {"enable_thinking": True, "preserve_thinking": True}
    return {"enable_thinking": False, "temperature": temperature}
