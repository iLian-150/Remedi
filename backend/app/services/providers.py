# LLM Provider 抽象层。
#   - LLMProvider：抽象类，定义 classify_error / score_essay / generate_feedback
#   - CloudflareProvider：统一调用 Cloudflare Workers AI；未配置凭证或调用失败时明确报错，
#     不返回 Mock 模拟结果。
import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _as_bool(value, default: bool = False) -> bool:
    """将视觉模型 JSON 的布尔字段归一化，避免 bool("false") 被误判为 True。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on", "是", "有"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", "否", "没有", ""}:
            return False
    return default


class LLMProvider(ABC):
    @abstractmethod
    def classify_error(self, *, question_stem: str, knowledge_point: str,
                       prev_step: str, curr_step: str, rule_result: Dict) -> Dict:
        """错因分类复核。输入规则分类结果，可确认、微调或改写。
        返回 {error_type, confidence, detail}。"""

    @abstractmethod
    def score_essay(self, *, text: str, prompt: Optional[str] = None) -> Dict:
        """英语作文评分。返回 {scores:{content,structure,grammar,vocabulary,expression,total},
        grammar_issues:[{sentence_no,sentence,issue,suggestion}], overall}。"""

    @abstractmethod
    def generate_feedback(self, *, student_name: str, summary: Dict) -> str:
        """按学习画像生成一句话学习建议。summary 含 knowledge_points / stubborn_errors 等。"""

    @abstractmethod
    def transcribe_image(self, image_bytes: bytes, content_type: str,
                         question_context: str = "", question_only: bool = False) -> Dict:
        """读取作业原图，返回题干、步骤和视觉识别质量信息。"""

    def diagnose_math_image(self, image_bytes: bytes, content_type: str,
                            question_context: str = "") -> Dict:
        """直接基于作业原图判断学生步骤对错，不依赖文本公式解析器。"""
        raise RuntimeError("当前模型 Provider 不支持数学作业图片诊断")

    def generate_variant_question(self, *, knowledge_point: str) -> Dict:
        """模型 Provider 未实现出题时明确报错，不返回预置题目。"""
        raise RuntimeError("当前模型 Provider 不支持生成变式题")

    def guess_knowledge_point(self, question_stem: str) -> str:
        """按题干猜知识点名（v0.13.0）：发布页知识点栏「AI 识别」的兜底实现。

        关键词启发式（离线可用）；命中不了返回空串，前端会提示教师手动填。
        真实 Provider（DeepSeekProvider 及继承它的 Cloudflare）覆写为文本模型判断。
        结果只是建议：教师可改，且知识点归类不经过它判对错。"""
        s = question_stem or ""
        rules = [
            (("勾股", "斜边", "直角边", "Rt△"), "勾股定理"),
            (("√", "根式", "根号"), "二次根式"),
            (("概率", "随机", "摸球", "掷骰"), "概率初步"),
            (("不等式",), "一元一次不等式"),
            (("因式分解", "分解因式"), "因式分解"),
            (("全等", "相似", "三角形"), "三角形"),
            (("函数", "图象", "图像"), "一次函数"),
            (("方程", "="), "一元一次方程"),
        ]
        for keys, name in rules:
            if any(k in s for k in keys):
                return name
        return ""

    def extract_questions_from_page(self, image_bytes: bytes, content_type: str,
                                    hint: str = "") -> List[Dict]:
        """从练习册页面图里提取题目草稿（v0.13.0）：返回 [{prompt, knowledge_point}]。

        未实现视觉识别的 Provider 明确报错；CloudflareProvider 由视觉模型逐页拆题。
        契约：返回值永远只是草稿——发布前必须由教师在题目卡里检查修改。"""
        raise RuntimeError("当前模型 Provider 不支持练习册页面识别")

    def transcribe_group_image(self, image_bytes: bytes, content_type: str) -> Dict:
        """拍照识别大题（v0.13.11）：一张图 → {stem, sub_questions:[{question_text, steps}]}。

        未实现视觉识别的 Provider 明确报错；CloudflareProvider 由视觉模型一次拆出共同题干与全部小题——
        识别入口在大题层级，不再逐个小题拍照。与单题转写同一契约：
        返回值永远只是草稿，教师检查修改后才发布。"""
        raise RuntimeError("当前模型 Provider 不支持大题图片识别")


# ---------------------------------------------------------------- DeepSeek

class DeepSeekProvider(LLMProvider):
    """调 OpenAI 兼容 Chat Completions。CloudflareProvider 复用此请求实现。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def _chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        import requests
        from ..config import settings

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _extract_json(text: str) -> Dict:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ValueError("模型未返回 JSON")
        return json.loads(m.group(0))

    def classify_error(self, *, question_stem, knowledge_point,
                       prev_step, curr_step, rule_result) -> Dict:
        try:
            out = self._chat(
                "你是数学错因分类助手。只返回 JSON，不要解释。",
                f"题干：{question_stem}\n知识点：{knowledge_point}\n"
                f"上一步（正确）：{prev_step}\n本步（学生作答，错误）：{curr_step}\n"
                f"规则分类结果：{json.dumps(rule_result, ensure_ascii=False)}\n"
                "请复核：返回 JSON {error_type: 计算失误|概念混淆|审题遗漏, "
                "confidence: 0~1, detail: 一句话中文说明}。",
            )
            data = self._extract_json(out)
            if data.get("error_type") not in ("计算失误", "概念混淆", "审题遗漏"):
                raise ValueError("error_type 非法")
            data["confidence"] = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
            return data
        except Exception as e:
            logger.exception("LLM classify_error 调用失败")
            raise RuntimeError("错因分类模型调用失败，请稍后重试") from e

    def score_essay(self, *, text, prompt=None) -> Dict:
        try:
            out = self._chat(
                "你是英语作文批改助手。只返回 JSON，不要解释。",
                f"作文题：{prompt or '自由写作'}\n作文：\n{text}\n"
                "请返回 JSON：{scores: {content, structure, grammar, vocabulary, expression "
                "(0~100 整数)}, grammar_issues: [{sentence_no, sentence, issue, suggestion}], "
                "overall: 中文总评}。",
                temperature=0.4,
            )
            data = self._extract_json(out)
            scores = data.get("scores", {})
            dims = ["content", "structure", "grammar", "vocabulary", "expression"]
            clean = {d: max(0, min(100, int(scores.get(d, 60)))) for d in dims}
            clean["total"] = round(sum(clean.values()) / 5)
            return {
                "scores": clean,
                "grammar_issues": data.get("grammar_issues", [])[:8],
                "overall": data.get("overall", ""),
            }
        except Exception as e:
            logger.exception("LLM score_essay 调用失败")
            raise RuntimeError("作文评分模型调用失败，请稍后重试") from e

    def generate_feedback(self, *, student_name, summary) -> str:
        try:
            return self._chat(
                "你是学习顾问，用中文给出一句话学习建议，亲切简洁。",
                f"学生：{student_name}\n学习画像：{json.dumps(summary, ensure_ascii=False, default=str)}",
            ).strip()
        except Exception as e:
            logger.exception("LLM generate_feedback 调用失败")
            raise RuntimeError("学习建议模型调用失败，请稍后重试") from e

    def transcribe_image(self, image_bytes: bytes, content_type: str,
                         question_context: str = "", question_only: bool = False) -> Dict:
        raise RuntimeError("当前模型不支持图片识别")

    def guess_knowledge_point(self, question_stem: str) -> str:
        """文本模型判断知识点名；答非所问/异常时退回基类关键词启发式（v0.13.0）。"""
        try:
            out = self._chat(
                "你是初中数学教研助手。只返回知识点名称本身，不要解释、不要标点、不要书名号。",
                "请判断这道题属于哪个初中数学知识点，只返回知识点名称"
                f"（如：一元一次方程、二次根式的加减、勾股定理）：\n{question_stem}",
                temperature=0.1,
            )
            name = (out or "").strip().splitlines()[0].strip(" :：。.\"'《》") if out else ""
            if 0 < len(name) <= 24:
                return name
        except Exception as e:
            logger.exception("知识点识别调用失败")
            raise RuntimeError("知识点识别模型调用失败，请稍后重试") from e
        raise RuntimeError("模型未返回有效的知识点名称，请稍后重试")

    def generate_variant_question(self, *, knowledge_point: str) -> Dict:
        """调模型为无模板的知识点生成同类题；异常或结构不合法时明确报错。"""
        try:
            out = self._chat(
                "你是数学出题助手。只返回 JSON，不要解释。",
                f"请为知识点「{knowledge_point}」出一道初中数学同类练习题，要求有明确的分步解法。\n"
                "返回 JSON：{prompt: 题干（以「解方程：」或「计算：」开头，公式用纯文本如 "
                "2x+3=7、(x+1)^2，不要 LaTeX）, standard_steps: 标准解题步骤数组"
                "（第一步为原式，其余为逐步变形，纯文本）, answer: 最终答案}。",
                temperature=0.7,
            )
            data = self._extract_json(out)
            steps = [str(s).strip() for s in data.get("standard_steps", []) if str(s).strip()]
            prompt = str(data.get("prompt", "")).strip()
            if not prompt or len(steps) < 2:
                raise ValueError("生成的题目结构不完整")
            return {
                "prompt": prompt,
                "standard_steps": steps,
                "answer": str(data.get("answer", "")).strip(),
            }
        except Exception as e:
            logger.exception("LLM generate_variant_question 调用失败")
            raise RuntimeError("变式题生成失败，请稍后重试") from e


# ---------------------------------------------------------------- Cloudflare Workers AI

class CloudflareProvider(DeepSeekProvider):
    """调 Cloudflare Workers AI 的 OpenAI 兼容接口。

    base_url 形如 https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1，
    其 /chat/completions 与 DeepSeek 的请求/响应结构一致，直接复用父类逻辑。
    默认模型 @cf/qwen/qwen3.8-27b（质量更高；单价约为旧 30b-a3b 的 9 倍，免费额度内约数十次对话/天）。
    未配置 account_id / token 时构造抛错；模型不可用时明确报错，不生成模拟内容。
    """

    def __init__(self, account_id: str, api_token: str, model: str,
                 vision_model: str = "@cf/qwen/qwen3.8-27b"):
        if not account_id or not api_token:
            raise RuntimeError("未配置 CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN")
        base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
        super().__init__(api_key=api_token, base_url=base_url, model=model)
        self.vision_model = vision_model
        self.account_id = account_id

    def _vision_text(self, data_url: str, system_text: str, prompt: str,
                     timeout: int) -> str:
        """视觉调用分流（v0.13.7）：统一返回模型的文本输出，JSON 解析由调用方做。

        - Moondream 3.1 不走 OpenAI 兼容的 /chat/completions，而是 Workers AI 的
          任务式接口 POST /ai/run/{model}，入参 {task:"query", image:<data URI>,
          question:<指令>, reasoning:false}，文本结果在 result.answer 里。
        - 其余聊天式视觉模型（如 llama 系列）继续走原来的 /chat/completions。
        """
        import requests
        if "moondream" in self.vision_model:
            resp = requests.post(
                "https://api.cloudflare.com/client/v4/accounts/{}/ai/run/{}".format(
                    self.account_id, self.vision_model),
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "task": "query",
                    "image": data_url,
                    "question": f"{system_text}\n{prompt}",
                    "reasoning": False,
                    "temperature": 0.1,
                    "max_tokens": 4096,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
            answer = (payload.get("result") or {}).get("answer")
            if not answer:
                raise RuntimeError(f"Moondream 未返回 answer: {str(payload)[:200]}")
            return str(answer)
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.vision_model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_text},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def transcribe_image(self, image_bytes: bytes, content_type: str,
                         question_context: str = "", question_only: bool = False) -> Dict:
        """视觉模型直接读取作答原图，并报告识别把握和作答证据。
        解析失败或请求异常时明确报错，不返回模拟转写。"""
        from ..config import settings

        try:
            data_url = "data:{};base64,{}".format(
                content_type or "image/jpeg",
                base64.b64encode(image_bytes).decode("ascii"),
            )
            prompt = (
                "请直接阅读这张作业原图，识别题目和学生作答。"
                f"已知题目参考：{question_context or '请从图片识别题目'}。"
                f"当前是{'自由上传题答疑' if question_only else '作业作答识别'}，请只按图片里的实际笔迹判断是否存在学生作答。"
                "题目放进 question_text；学生的作答步骤按顺序逐行放进 steps，steps 不要包含题干。"
                "数学公式用纯文本，如 2x+3=7、x=5，不要用 LaTeX。"
                "若图片模糊、裁切或无法可靠辨认，needs_image_review=true；"
                "若只有题目、没有学生作答，student_work_detected=false 且 steps 为空。"
                "confidence 为识别把握，取 0 到 1。"
                '只输出 JSON：{"question_text":"...","steps":["..."],'
                '"student_work_detected":true,"needs_image_review":false,"confidence":0.9}'
            )
            content = self._vision_text(
                data_url,
                "你是作业照片理解助手。只返回 JSON，不要解释、不要 Markdown 代码块。",
                prompt,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            data = self._extract_json(content)
            steps = [str(s).strip() for s in data.get("steps", []) if str(s).strip()]
            question_text = str(data.get("question_text", "")).strip()
            try:
                confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            except (TypeError, ValueError):
                confidence = 0.0
            return {
                "question_text": question_text,
                "steps": steps,
                "student_work_detected": _as_bool(
                    data.get("student_work_detected"), default=bool(steps)
                ),
                "needs_image_review": _as_bool(
                    data.get("needs_image_review"), default=not steps
                ),
                "confidence": confidence,
            }
        except Exception as e:
            logger.exception("LLM transcribe_image 调用失败")
            raise RuntimeError("图片识别失败，请检查图片后重试") from e

    def diagnose_math_image(self, image_bytes: bytes, content_type: str,
                            question_context: str = "") -> Dict:
        """让视觉模型直接阅读题目与作答，并逐步判断正误和错因。"""
        from ..config import settings

        try:
            data_url = "data:{};base64,{}".format(
                content_type or "image/jpeg",
                base64.b64encode(image_bytes).decode("ascii"),
            )
            prompt = (
                "请直接观察这张数学作业原图，同时理解题目、学生实际作答和图形信息，完成批改。"
                f"已知题目参考：{question_context or '请从图片中理解题目'}。"
                "请依据图像中的完整解题过程判断每一步是否正确，不要先把整张图片逐行转写后再用公式匹配来推断。"
                "steps 只列学生本人写出的解题过程或答案，不要把印刷题干、参考答案、教师红笔勾叉当成学生步骤。"
                "result 只能是 correct、incorrect、uncertain；判断不清时选 uncertain，并把 confidence 设为 0 到 0.59。"
                "对 incorrect 步骤，error_type 只能是 计算失误、概念混淆、审题遗漏、无法解析，并用中文简要说明证据；"
                "对 correct 步骤，error_type 和 detail 留空。逐步给出判断 confidence（0 到 1）。"
                "若照片模糊、裁切，或题目/作答无法可靠辨认，needs_image_review=true；单纯错因把握低不代表图像模糊。"
                "若只有题目而没有学生作答，student_work_detected=false 且 steps 为空。"
                "confidence 表示图像中题目和作答的整体可辨认度，不表示错因把握。"
                "knowledge_point 填一个简短、具体的数学知识点名称；若题目无法确定则留空。"
                '只返回 JSON：{"question_text":"题目内容","student_work_detected":true,'
                '"knowledge_point":"一元一次方程","needs_image_review":false,"confidence":0.95,"steps":['
                '{"text":"学生原步骤","result":"correct","confidence":0.95,"error_type":"","detail":""},'
                '{"text":"学生错误步骤","result":"incorrect","confidence":0.82,"error_type":"计算失误","detail":"说明错误和判断依据"}]}。'
            )
            content = self._vision_text(
                data_url,
                "你是严谨的数学作业视觉诊断助手。直接分析图片证据，只返回 JSON，不要解释或 Markdown。",
                prompt,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            data = self._extract_json(content)
            raw_steps = data.get("steps", [])
            if not isinstance(raw_steps, list):
                raise ValueError("steps 必须是数组")

            steps = []
            for item in raw_steps:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                result = str(item.get("result", "uncertain")).strip().lower()
                if result in {"正确", "对", "correct"}:
                    result = "correct"
                elif result in {"错误", "错", "incorrect", "wrong"}:
                    result = "incorrect"
                else:
                    result = "uncertain"
                try:
                    step_confidence = max(0.0, min(1.0, float(item.get("confidence", 0.5))))
                except (TypeError, ValueError):
                    step_confidence = 0.5
                error_type = str(item.get("error_type", "")).strip()
                if error_type not in {"计算失误", "概念混淆", "审题遗漏", "无法解析"}:
                    error_type = "无法解析" if result == "uncertain" else "审题遗漏"
                steps.append({
                    "text": text[:500],
                    "result": result,
                    "confidence": step_confidence,
                    "error_type": error_type,
                    "detail": str(item.get("detail", "")).strip()[:1000],
                })

            try:
                image_confidence = max(0.0, min(1.0, float(data.get("confidence", 0.0))))
            except (TypeError, ValueError):
                image_confidence = 0.0
            question_text = str(data.get("question_text", "")).strip() or question_context
            knowledge_point = str(data.get("knowledge_point", "")).strip()[:64]
            return {
                "question_text": question_text[:12000],
                "knowledge_point": knowledge_point,
                "steps": steps,
                "student_work_detected": _as_bool(
                    data.get("student_work_detected"), default=bool(steps)
                ),
                "needs_image_review": _as_bool(
                    data.get("needs_image_review"), default=not steps and not question_text
                ),
                "confidence": image_confidence,
            }
        except Exception as e:
            logger.exception("视觉模型数学作业诊断失败")
            raise RuntimeError("图片诊断失败，请检查图片或稍后重试") from e

    def transcribe_group_image(self, image_bytes: bytes, content_type: str) -> Dict:
        """视觉模型识别大题（v0.13.11）：共同题干 + 全部小题一次拆出。

        照片通常是大题原题（可能带印刷/手写解题过程）：stem 放共同材料，
        每道小题的题干放 question_text；照片里有该小题的解题过程才填 steps，
        没有就留空数组（教师后续可补标准步骤）。解析失败或请求异常时明确报错。"""
        from ..config import settings

        try:
            data_url = "data:{};base64,{}".format(
                content_type or "image/jpeg",
                base64.b64encode(image_bytes).decode("ascii"),
            )
            prompt = (
                "请直接阅读这张照片，它是一道数学大题：一段共同题干（材料）下面挂着几道小题。"
                "把共同题干放进 stem（不要把任何一道小题的题干混进 stem）；"
                "每道小题的题干放进 sub_questions 的 question_text，按照片里的顺序；"
                "如果照片里有这道小题的解题过程（手写或印刷都算），按顺序逐行放进它的 steps，"
                "没有解题过程就给空数组。"
                "数学公式用纯文本，如 y = kx + b、x = -2，不要用 LaTeX。"
                '只输出 JSON：{"stem":"...","sub_questions":[{"question_text":"...","steps":["..."]}]}'
            )
            content = self._vision_text(
                data_url,
                "你是作业照片理解助手。只返回 JSON，不要解释、不要 Markdown 代码块。",
                prompt,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            data = self._extract_json(content)
            stem = str(data.get("stem", "")).strip()
            subs: List[Dict] = []
            for raw in data.get("sub_questions") or []:
                if not isinstance(raw, dict):
                    continue
                qt = str(raw.get("question_text") or raw.get("prompt") or "").strip()
                if not qt:
                    continue
                steps = [str(s).strip() for s in (raw.get("steps") or []) if str(s).strip()]
                subs.append({"question_text": qt, "steps": steps})
            if not stem and not subs:
                raise ValueError("大题识别结果为空")
            return {"stem": stem, "sub_questions": subs}
        except Exception as e:
            logger.exception("LLM transcribe_group_image 调用失败")
            raise RuntimeError("大题图片识别失败，请稍后重试") from e


    def extract_questions_from_page(self, image_bytes: bytes, content_type: str,
                                    hint: str = "") -> List[Dict]:
        """视觉模型逐页拆题（v0.13.0）：一页练习册图 → 多道题目草稿。

        与 transcribe_image 的区别：那是单题+学生作答的转写；这里只要题干，
        一页多题全部提取、按页面顺序返回。异常或无效结果时明确报错。"""
        from ..config import settings

        try:
            data_url = "data:{};base64,{}".format(
                content_type or "image/jpeg",
                base64.b64encode(image_bytes).decode("ascii"),
            )
            prompt = (
                "这是一页数学练习册或教材的页面图。请把这一页上所有独立的题目逐道提取出来，按在页面上出现的顺序排列。"
                "只要题干，不要例题的讲解文字和解答过程；一道题有多个小问时合并成一道，题干里保留小问编号。"
                "为每道题猜一个 knowledge_point（初中数学知识点名，如「一元一次方程」「二次根式的加减」），猜不到就给空字符串。"
                "数学公式用纯文本（如 2x+3=7、√12、x²），不要用 LaTeX。"
            )
            if hint:
                prompt += f"老师给的范围提示：{hint}，优先提取这些题。"
            prompt += '只输出 JSON：{"questions":[{"prompt":"...","knowledge_point":"..."}]}。这一页没有题目就输出 {"questions":[]}。'
            content = self._vision_text(
                data_url,
                "你是练习册题目提取助手。只返回 JSON，不要解释、不要 Markdown 代码块。",
                prompt,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            data = self._extract_json(content)
            out: List[Dict] = []
            for item in data.get("questions", []) or []:
                if isinstance(item, dict):
                    p = str(item.get("prompt", "")).strip()
                    if p:
                        out.append({
                            "prompt": p,
                            "knowledge_point": str(item.get("knowledge_point", "")).strip(),
                        })
                elif isinstance(item, str) and item.strip():
                    out.append({"prompt": item.strip(), "knowledge_point": ""})
            return out
        except Exception as e:
            logger.exception("LLM 页面提题调用失败")
            raise RuntimeError("练习册页面识别失败，请稍后重试") from e


# ---------------------------------------------------------------- 工厂

_provider = None


def get_provider() -> LLMProvider:
    """只返回 Cloudflare Provider；配置或服务异常时抛错，不自动切换到模拟实现。"""
    global _provider
    if _provider is not None:
        return _provider
    from ..config import settings
    if settings.LLM_PROVIDER != "cloudflare":
        raise RuntimeError("LLM_PROVIDER 必须设为 cloudflare，当前不提供 Mock 或其他模型")
    _provider = CloudflareProvider(
        account_id=settings.CLOUDFLARE_ACCOUNT_ID,
        api_token=settings.CLOUDFLARE_API_TOKEN,
        model=settings.CLOUDFLARE_MODEL,
        vision_model=settings.CLOUDFLARE_VISION_MODEL,
    )
    logger.info("LLM Provider: cloudflare (%s)", settings.CLOUDFLARE_MODEL)
    return _provider


def reset_provider():
    """测试用：清空缓存的 provider。"""
    global _provider
    _provider = None
