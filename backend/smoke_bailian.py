"""百炼文本、视觉及 Agent 请求回归；所有网络调用均被替身拦截。"""
import base64
import json
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.messages.utils import message_chunk_to_message

from app.config import settings
from app.agent.graph import _build_llm, _message_chunk_text
from app.services import providers
from app.services.bailian_options import bailian_request_options


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

    def assert_request(self, request, *, model, thinking=False):
        self.assertEqual(request.args[0], settings.DASHSCOPE_BASE_URL + "/chat/completions")
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer unit-test-only-key")
        self.assertEqual(request.kwargs["json"]["model"], model)
        self.assertIs(request.kwargs["json"]["enable_thinking"], thinking)
        if thinking:
            self.assertIs(request.kwargs["json"]["preserve_thinking"], True)
            self.assertNotIn("temperature", request.kwargs["json"])
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

    def test_request_options_are_selected_for_actual_model(self):
        for name in ("kimi-k3", "kimi/kimi-k3", "kimi-k3-2026-09-01"):
            with self.subTest(model=name):
                self.assertEqual(bailian_request_options(name, 0.2),
                                 {"enable_thinking": True, "preserve_thinking": True})
        for name in ("qwen-plus", "qwen3-vl-plus"):
            with self.subTest(model=name):
                self.assertEqual(bailian_request_options(name, 0.2),
                                 {"enable_thinking": False, "temperature": 0.2})

    def test_kimi_text_uses_preserved_thinking_but_qwen_image_does_not(self):
        text_response = self.response("最终回复")
        text_response.json.return_value["choices"][0]["message"]["reasoning_content"] = "仅供模型继续推理"
        stream_response = self.response(lines=[self.sse({"reasoning_content": "仅供模型继续推理"}),
                                               self.sse({"content": "最终回复"}), b"data: [DONE]"])
        image_response = self.response(json.dumps({"question_text": "x=1", "steps": []}))
        with patch.object(settings, "DASHSCOPE_MODEL", "kimi-k3"), patch(
            "requests.post", side_effect=[text_response, stream_response, image_response],
        ) as post:
            provider = self.provider()
            self.assertEqual(provider._chat("要求", "题目", temperature=0.2), "最终回复")
            self.assertEqual(list(provider.stream_chat_answer("要求", "题目", temperature=0)), ["最终回复"])
            provider.transcribe_image(b"image", "image/png")
        self.assert_request(post.call_args_list[0], model="kimi-k3", thinking=True)
        self.assert_request(post.call_args_list[1], model="kimi-k3", thinking=True)
        self.assert_request(post.call_args_list[2], model="qwen3-vl-plus")
        self.assertEqual(post.call_args_list[2].kwargs["json"]["temperature"], 0.1)

    def test_future_kimi_vision_uses_its_own_model_options(self):
        image_response = self.response(json.dumps({"question_text": "x=1", "steps": []}))
        stream_response = self.response(lines=[self.sse({"reasoning_content": "推理片段"}),
                                               self.sse({"content": "图片讲解"}), b"data: [DONE]"])
        with patch.object(settings, "DASHSCOPE_VISION_MODEL", "kimi-k3"), patch(
            "requests.post", side_effect=[image_response, stream_response],
        ) as post:
            provider = self.provider()
            self.assertEqual(provider.model, "qwen-plus")
            provider.transcribe_image(b"image", "image/png")
            self.assertEqual(list(provider.stream_image_answer(b"image", "image/png")), ["图片讲解"])
        for request in post.call_args_list:
            self.assert_request(request, model="kimi-k3", thinking=True)

    def test_kimi_stream_and_sync_reasoning_roundtrip_across_tool_calls(self):
        with patch.object(settings, "DASHSCOPE_MODEL", "kimi-k3"):
            llm = _build_llm(streaming=True, temperature=0)
        self.assertEqual(llm.extra_body, {"enable_thinking": True, "preserve_thinking": True})
        self.assertIsNone(llm.temperature)
        self.assertFalse(llm.use_responses_api)
        first = llm._convert_chunk_to_generation_chunk(
            {"choices": [{"delta": {"role": "assistant", "content": None,
                                      "reasoning_content": "先读取报告。"}}]}, AIMessageChunk, {},
        )
        second = llm._convert_chunk_to_generation_chunk(
            {"choices": [{"delta": {"content": None, "reasoning_content": "再查询错题。", "tool_calls": [
                {"index": 0, "id": "call-report", "type": "function",
                 "function": {"name": "read_report", "arguments": "{}"}},
            ]}, "finish_reason": "tool_calls"}]}, AIMessageChunk, {},
        )
        assistant = message_chunk_to_message((first + second).message)
        self.assertEqual(assistant.additional_kwargs["reasoning_content"], "先读取报告。再查询错题。")
        self.assertEqual(_message_chunk_text(assistant), "", "推理字段不能作为用户可见文字")
        messages = [HumanMessage(content="帮我看看薄弱点"), assistant,
                    ToolMessage(content="报告数据", tool_call_id="call-report")]
        payload = llm._get_request_payload(messages)
        self.assertNotIn("temperature", payload)
        self.assertEqual(payload["messages"][1]["reasoning_content"], "先读取报告。再查询错题。")
        self.assertEqual(payload["messages"][1]["tool_calls"][0]["id"], "call-report")
        self.assertEqual(payload["messages"][2]["tool_call_id"], "call-report")
        self.assertNotIn("reasoning_content", payload["messages"][0])

        raw = {"model": "kimi-k3", "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": None, "reasoning_content": "同步读取报告。",
            "tool_calls": [{"id": "sync-report", "type": "function",
                            "function": {"name": "read_report", "arguments": "{}"}}],
        }}]}
        synchronous = llm._create_chat_result(raw).generations[0].message
        self.assertEqual(synchronous.additional_kwargs["reasoning_content"], "同步读取报告。")
        next_payload = llm._get_request_payload([HumanMessage(content="报告"), synchronous,
                                                ToolMessage(content="数据", tool_call_id="sync-report")])
        self.assertEqual(next_payload["messages"][1]["reasoning_content"], "同步读取报告。")
        raw["choices"][0]["message"].update(content="最终回答", tool_calls=[])
        final_answer = llm._create_chat_result(raw).generations[0].message
        self.assertEqual(_message_chunk_text(final_answer), "最终回答")
        historical = llm._get_request_payload([AIMessage(content="旧回复"), HumanMessage(content="追问")])
        self.assertNotIn("reasoning_content", historical["messages"][0], "旧记录不得编造推理字段")
        self.network.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
