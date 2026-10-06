# LLM Provider 抽象层。
#   - LLMProvider：抽象类，定义 classify_error / score_essay / generate_feedback
#   - MockProvider：确定性返回，无需 key，保证全流程可跑（默认）
#   - DeepSeekProvider：调 DeepSeek Chat Completions；未配置 DEEPSEEK_API_KEY
#     或请求异常时自动降级为 Mock，保证流程不中断
# 切换：环境变量 LLM_PROVIDER=mock|deepseek（默认 mock）
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------- Mock（确定性）

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_LINKING_WORDS = {
    "first", "firstly", "second", "secondly", "third", "then", "next",
    "however", "but", "because", "so", "and", "also", "finally",
    "in addition", "for example", "such as", "although", "though",
}


class MockProvider(LLMProvider):
    """确定性 Mock：classify 原样返回规则结果；作文用启发式打分；建议用模板。"""

    def classify_error(self, *, question_stem, knowledge_point,
                       prev_step, curr_step, rule_result) -> Dict:
        result = dict(rule_result)
        result["detail"] = (result.get("detail") or "") + "（规则分类，Mock 未改写）"
        return result

    # -- 作文轻量评分（确定性启发式） --
    def score_essay(self, *, text, prompt=None) -> Dict:
        sentences = [s.strip() for s in _SENT_SPLIT_RE.split(text.strip()) if s.strip()]
        words = re.findall(r"[A-Za-z']+", text.lower())
        n_words = len(words)
        n_sent = max(len(sentences), 1)

        issues = self._grammar_check(sentences)

        # 内容：按词数覆盖度（默认目标 60~80 词，可从 prompt 里解析 "60-80 words"）
        target_min, target_max = 60, 80
        if prompt:
            m = re.search(r"(\d+)\s*[-~]\s*(\d+)\s*words", prompt)
            if m:
                target_min, target_max = int(m.group(1)), int(m.group(2))
        if n_words < target_min:
            content = int(40 + 50 * n_words / target_min)
        elif n_words <= target_max:
            content = 90
        else:
            content = max(70, 90 - (n_words - target_max) // 4)

        # 结构：分段 + 连接词
        paragraphs = [p for p in text.split("\n") if p.strip()]
        linking = sum(1 for w in _LINKING_WORDS if w in text.lower())
        structure = min(95, 55 + (8 if len(paragraphs) >= 2 else 0) + min(linking, 4) * 8)

        # 语法：按问题数扣分
        grammar = max(40, 100 - 12 * len(issues))

        # 词汇：类符/形符比
        ttr = len(set(words)) / n_words if n_words else 0
        vocabulary = min(95, int(45 + ttr * 80))

        # 表达：平均句长 8~18 词最佳
        avg_len = n_words / n_sent
        if 8 <= avg_len <= 18:
            expression = 85
        elif avg_len < 8:
            expression = int(60 + avg_len * 3)
        else:
            expression = max(55, int(85 - (avg_len - 18) * 2))

        scores = {
            "content": max(0, min(100, content)),
            "structure": max(0, min(100, structure)),
            "grammar": grammar,
            "vocabulary": max(0, min(100, vocabulary)),
            "expression": max(0, min(100, expression)),
        }
        scores["total"] = round(sum(scores.values()) / 5)

        overall = (
            f"全文 {n_words} 词、{len(sentences)} 句。内容{'完整' if scores['content'] >= 80 else '基本完整' if scores['content'] >= 60 else '偏少，建议补充细节'}；"
            f"发现 {len(issues)} 处疑似语法问题{'，已在下方标出' if issues else ''}。"
            f"{'建议多使用连接词（however / because / for example）提升结构分。' if scores['structure'] < 75 else ''}"
            f"{'注意丰富词汇，避免重复用词。' if scores['vocabulary'] < 70 else ''}"
        )
        return {"scores": scores, "grammar_issues": issues, "overall": overall}

    def _grammar_check(self, sentences: List[str]) -> List[Dict]:
        issues = []
        for idx, s in enumerate(sentences, start=1):
            if len(issues) >= 8:
                break
            # 1. 冠词 a + 元音开头
            if re.search(r"\ba\s+[aeiouAEIOU]", s):
                issues.append({
                    "sentence_no": idx, "sentence": s,
                    "issue": "冠词误用：a 后接元音开头的词",
                    "suggestion": "a → an",
                })
                continue
            # 2. 第三人称单数动词未加 -s（he/she/it + 原形常见动词）
            m = re.search(r"\b(he|she|it)\s+(go|have|do|make|like|want|need|play|watch)\b", s, re.I)
            if m:
                verb = m.group(2)
                fixed = {"go": "goes", "have": "has", "do": "does"}.get(verb.lower(), verb + "s")
                issues.append({
                    "sentence_no": idx, "sentence": s,
                    "issue": "第三人称单数作主语时，动词未加 -s",
                    "suggestion": f"{verb} → {fixed}",
                })
                continue
            # 3. 重复单词
            m = re.search(r"\b(\w+)\s+\1\b", s, re.I)
            if m:
                issues.append({
                    "sentence_no": idx, "sentence": s,
                    "issue": f"单词重复：{m.group(1)}",
                    "suggestion": "删除多余的一个",
                })
                continue
            # 4. 句首未大写
            if s and s[0].isalpha() and not s[0].isupper():
                issues.append({
                    "sentence_no": idx, "sentence": s,
                    "issue": "句首字母未大写",
                    "suggestion": "句首字母改为大写",
                })
                continue
            # 5. 缺少结尾标点
            if s and s[-1] not in ".!?":
                issues.append({
                    "sentence_no": idx, "sentence": s,
                    "issue": "句子缺少结尾标点",
                    "suggestion": "句末加上 . / ! / ?",
                })
        return issues

    def generate_feedback(self, *, student_name: str, summary: Dict) -> str:
        kps = summary.get("knowledge_points", []) or []
        stubborn = summary.get("stubborn_errors", []) or []
        weak = sorted(kps, key=lambda k: k.get("mastery", 1))[:1]
        parts = []
        if stubborn:
            kp_names = sorted({e.get("knowledge_point", "") for e in stubborn if e.get("knowledge_point")})
            parts.append(f"在「{'、'.join(kp_names)}」上存在顽固误区（30 天内重复出错），建议先重看对应规则，再做 3 道针对性练习")
        if weak and weak[0].get("mastery", 1) < 0.6:
            wk = weak[0]["knowledge_point"]
            if not any(wk in p for p in parts):
                parts.append(f"「{wk}」掌握度仅 {weak[0]['mastery']:.0%}，是当前最弱环节")
        if not parts:
            parts.append("整体表现稳定，继续保持；可尝试更高难度的综合题")
        return f"{student_name}，" + "；".join(parts) + "。"


# ---------------------------------------------------------------- DeepSeek

class DeepSeekProvider(LLMProvider):
    """调 DeepSeek Chat Completions。构造时无 key 直接抛错，由工厂降级为 Mock。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._mock = MockProvider()  # 异常时的兜底

    def _chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        import requests
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
            timeout=30,
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
            logger.warning("DeepSeek classify_error 失败，降级为规则结果: %s", e)
            return dict(rule_result)

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
            logger.warning("DeepSeek score_essay 失败，降级为 Mock: %s", e)
            return self._mock.score_essay(text=text, prompt=prompt)

    def generate_feedback(self, *, student_name, summary) -> str:
        try:
            return self._chat(
                "你是学习顾问，用中文给出一句话学习建议，亲切简洁。",
                f"学生：{student_name}\n学习画像：{json.dumps(summary, ensure_ascii=False, default=str)}",
            ).strip()
        except Exception as e:
            logger.warning("DeepSeek generate_feedback 失败，降级为 Mock: %s", e)
            return self._mock.generate_feedback(student_name=student_name, summary=summary)


# ---------------------------------------------------------------- 工厂

_provider = None


def get_provider() -> LLMProvider:
    """按 LLM_PROVIDER 选择实现；deepseek 未配置 key 时自动降级 mock。"""
    global _provider
    if _provider is not None:
        return _provider
    from ..config import settings
    if settings.LLM_PROVIDER == "deepseek":
        try:
            _provider = DeepSeekProvider(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                model=settings.DEEPSEEK_MODEL,
            )
            logger.info("LLM Provider: deepseek (%s)", settings.DEEPSEEK_MODEL)
        except Exception as e:
            logger.warning("DeepSeek 初始化失败（%s），自动降级为 Mock", e)
            _provider = MockProvider()
    else:
        _provider = MockProvider()
        logger.info("LLM Provider: mock")
    return _provider


def reset_provider():
    """测试用：清空缓存的 provider。"""
    global _provider
    _provider = None
