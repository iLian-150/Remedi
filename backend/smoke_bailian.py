"""百炼文本、视觉及 Agent 请求回归；所有网络调用均被替身拦截。"""
import base64
import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import HumanMessage

from app.config import settings
from app.agent.graph import _build_llm
from app.services import providers


class BailianTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.multiple(
            settings,
            LLM_PROVIDER="bailian", DASHSCOPE_API_KEY="unit-test-only-key",
            DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1",
            DASHSCOPE_MODEL="qwen-plus", DASHSCOPE_VISION_MODEL="qwen3-vl-plus",
            LLM_TIMEOUT_SECONDS=25, create=True,
        ))
        self.enterContext(patch.object(providers, "_provider", None))
        self.network = self.enterContext(patch("requests.post", side_effect=AssertionError("unexpected HTTP call")))
        self.enterContext(patch("httpx.Client.send", side_effect=AssertionError("unexpected SDK call")))

    def response(self, content=None, lines=None):
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": content}}]}
        if lines is not None:
            response.iter_lines.return_value = lines
        return response

    @staticmethod
    def sse(delta):
        return ("data: " + json.dumps({"choices": [{"delta": delta}]})).encode()

    def provider(self):
        return providers.get_provider()

    def assert_request(self, request, *, model):
        self.assertEqual(request.args[0], settings.DASHSCOPE_BASE_URL + "/chat/completions")
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer unit-test-only-key")
        self.assertEqual(request.kwargs["json"]["model"], model)
        self.assertIs(request.kwargs["json"]["enable_thinking"], False)
        self.assertNotIn("extra_body", request.kwargs["json"], "直接 HTTP 调用的自定义参数应处于顶层")

    def test_active_factory_uses_bailian_and_accepts_provider_aliases(self):
        for provider_name in ("bailian", "dashscope", "aliyun"):
            with self.subTest(provider_name=provider_name), patch.object(settings, "LLM_PROVIDER", provider_name):
                providers.reset_provider()
                provider = self.provider()
                self.assertIsInstance(provider, providers.BailianProvider)
                self.assertNotIsInstance(provider, providers.CloudflareProvider)
                self.assertEqual(provider.model, "qwen-plus")
                self.assertEqual(provider.vision_model, "qwen3-vl-plus")
                self.assertIs(self.provider(), provider)
        self.network.assert_not_called()

    def test_blank_key_fails_without_network_or_fallback(self):
        with patch.object(settings, "DASHSCOPE_API_KEY", ""), patch.object(
            providers, "CloudflareProvider", side_effect=AssertionError("must not fall back to Cloudflare"),
        ):
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                self.provider()
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                _build_llm()
            with self.assertRaisesRegex(RuntimeError, "DASHSCOPE_API_KEY"):
                providers.BailianProvider("  ", settings.DASHSCOPE_BASE_URL, "qwen-plus")
        self.network.assert_not_called()

    def test_inactive_provider_is_rejected(self):
        with patch.object(settings, "LLM_PROVIDER", "cloudflare"):
            with self.assertRaisesRegex(RuntimeError, "bailian"):
                self.provider()
            with self.assertRaisesRegex(RuntimeError, "bailian"):
                _build_llm()
        self.network.assert_not_called()

    def test_text_payload_uses_bailian_chat_endpoint_and_disables_thinking(self):
        with patch("requests.post", return_value=self.response("真实模型文本")) as post:
            result = self.provider()._chat("系统教学要求", "用户题目", temperature=0.2)
        self.assertEqual(result, "真实模型文本")
        self.assert_request(post.call_args, model="qwen-plus")
        self.assertEqual(post.call_args.kwargs["json"]["messages"], [
            {"role": "system", "content": "系统教学要求"}, {"role": "user", "content": "用户题目"},
        ])
        self.assertEqual(post.call_args.kwargs["timeout"], 25)

    def test_image_recognition_uses_standard_image_url_payload(self):
        image = b"test-image-bytes"
        model_result = json.dumps({"question_text": "x+1=2", "steps": ["x=1"],
                                   "student_work_detected": True, "needs_image_review": False, "confidence": 0.95})
        with patch("requests.post", return_value=self.response(model_result)) as post:
            result = self.provider().transcribe_image(image, "image/png", "数学题")
        self.assertEqual(result["steps"], ["x=1"])
        self.assert_request(post.call_args, model="qwen3-vl-plus")
        content = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertEqual(content[1], {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
        }})
        self.assertNotIn("task", post.call_args.kwargs["json"], "百炼不得调用 Workers 专属任务接口")

    def test_image_sse_streams_only_model_text_and_closes_response(self):
        response = self.response(lines=[
            b": keepalive", self.sse({"reasoning_content": "hidden reasoning"}),
            self.sse({"content": "第一步"}),
            self.sse({"content": [{"type": "text", "text": "，列方程。"}]}),
            b'data: {"choices":[],"usage":{}}', b"data: [DONE]",
        ])
        with patch("requests.post", return_value=response) as post:
            chunks = list(self.provider().stream_image_answer(b"image", "image/jpeg", "请讲解"))
        self.assertEqual(chunks, ["第一步", "，列方程。"])
        self.assert_request(post.call_args, model="qwen3-vl-plus")
        self.assertTrue(post.call_args.kwargs["stream"])
        self.assertTrue(post.call_args.kwargs["json"]["stream"])
        response.close.assert_called_once()

    def test_text_sse_uses_bailian_and_closes_on_failure(self):
        response = self.response(lines=[self.sse({"content": "真实文本"}), b"data: not-json"])
        with patch("requests.post", return_value=response) as post:
            stream = self.provider().stream_chat_answer("教学要求", "题目")
            self.assertEqual(next(stream), "真实文本")
            with self.assertRaises(ValueError):
                next(stream)
        self.assert_request(post.call_args, model="qwen-plus")
        response.close.assert_called_once()

    def test_workbook_page_and_group_extraction_share_bailian_vision(self):
        page = json.dumps({"questions": [{"prompt": "解方程 x+1=2", "knowledge_point": "一元一次方程"}]})
        group = json.dumps({"stem": "共同题干", "sub_questions": [{"question_text": "求x", "steps": []}]})
        with patch("requests.post", side_effect=[self.response(page), self.response(group)]) as post:
            provider = self.provider()
            questions = provider.extract_questions_from_page(b"page", "image/png", "第一题")
            result = provider.transcribe_group_image(b"group", "image/png")
        self.assertEqual(questions[0]["knowledge_point"], "一元一次方程")
        self.assertEqual(result["stem"], "共同题干")
        for request in post.call_args_list:
            self.assert_request(request, model="qwen3-vl-plus")

    def test_langgraph_model_uses_bailian_non_thinking_chat_and_tools(self):
        llm = _build_llm(streaming=True, temperature=0.4, timeout_seconds=9)
        self.assertEqual(llm.openai_api_base, settings.DASHSCOPE_BASE_URL)
        self.assertEqual(llm.model_name, "qwen-plus")
        self.assertEqual(llm.extra_body, {"enable_thinking": False})
        self.assertEqual(llm.request_timeout, 9)
        self.assertEqual(llm.max_retries, 0)
        self.assertTrue(llm.streaming)
        self.assertFalse(llm.use_responses_api)
        tool = {"type": "function", "function": {"name": "read_report", "description": "读取报告",
                                                   "parameters": {"type": "object", "properties": {}}}}
        bound = llm.bind_tools([tool])
        payload = llm._get_request_payload([HumanMessage(content="读取报告")], **bound.kwargs)
        self.assertEqual(payload["model"], "qwen-plus")
        self.assertEqual(payload["extra_body"], {"enable_thinking": False})
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["tools"][0]["function"]["name"], "read_report")
        synchronous = _build_llm(streaming=False, temperature=0)
        self.assertFalse(synchronous.streaming)
        self.assertEqual(synchronous.extra_body, {"enable_thinking": False})
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
