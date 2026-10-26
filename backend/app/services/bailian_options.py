"""百炼各请求模型的选项；纯函数，不读取凭证或访问网络。"""


def is_kimi_k3(model: str) -> bool:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name == "kimi-k3" or name.startswith("kimi-k3-")


def is_kimi_k26(model: str) -> bool:
    name = (model or "").strip().lower().rsplit("/", 1)[-1]
    return name == "kimi-k2.6" or name.startswith("kimi-k2.6-")


def bailian_request_options(model: str, temperature: float) -> dict:
    """使用各 Kimi 型号在百炼支持的思考与采样参数。

    K3 不可关闭思考，省略固定采样参数以使用服务端默认值。K2.6 支持
    非思考模式，但该模式的温度固定为 0.6。Qwen 保持原有参数。
    """
    if is_kimi_k3(model):
        return {"enable_thinking": True, "preserve_thinking": True}
    if is_kimi_k26(model):
        return {"enable_thinking": False, "temperature": 0.6}
    return {"enable_thinking": False, "temperature": temperature}
