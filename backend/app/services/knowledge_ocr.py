"""专用文字 OCR 与按需图形理解；不让视觉大模型承担全书逐字转写。"""
import csv
import io
import logging
import os
import re
import subprocess

from ..config import settings

logger = logging.getLogger(__name__)
_VISUAL_MARKERS = re.compile(
    r"如图|图中|图示|示意图|图象|图像|坐标系|流程图|统计图|结构图|电路图|"
    r"图\s*[0-9一二三四五六七八九十]|\b(?:figure|diagram|chart|graph)\b", re.I,
)


def recognize_text(image_bytes: bytes) -> dict:
    """Tesseract TSV 同时返回文字与可信度；独立子进程有明确期限。"""
    try:
        completed = subprocess.run(
            [settings.RAG_OCR_EXECUTABLE, "stdin", "stdout", "-l", settings.RAG_OCR_LANGUAGE,
             "--psm", "3", "tsv"],
            input=image_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=settings.RAG_OCR_TIMEOUT_SECONDS, check=False,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except FileNotFoundError:
        raise RuntimeError("专用 OCR 尚未安装或路径无效，请检查后端 OCR 配置。") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError("页面文字识别超时，可重试继续处理。") from None
    if completed.returncode:
        # stderr 可能包含文件路径或输入内容，不进入公开错误。
        raise RuntimeError("页面文字识别失败，请检查文件或 OCR 中文语言包。")
    lines = {}
    confidences = []
    for word in csv.DictReader(io.StringIO(completed.stdout.decode("utf-8", errors="replace")), delimiter="\t"):
        text = (word.get("text") or "").strip()
        if not text:
            continue
        key = tuple(word.get(k) for k in ("page_num", "block_num", "par_num", "line_num"))
        lines.setdefault(key, []).append(text)
        try:
            confidence = float(word.get("conf", -1))
            if confidence >= 0:
                confidences.append(confidence / 100)
        except (TypeError, ValueError):
            continue
    text = "\n".join(" ".join(words) for words in lines.values())
    # Tesseract 的中文单字不需要人为添加英文空格。
    text = re.sub(r"(?<=[\u4e00-\u9fff]) +(?=[\u4e00-\u9fff])", "", text).strip()
    return {"text": text, "confidence": sum(confidences) / len(confidences) if confidences else 0.0}


def needs_visual_context(text: str, confidence: float = 1.0) -> bool:
    return bool(_VISUAL_MARKERS.search(text or "")) or (
        confidence < 0.55 and bool(re.search(r"[=√△∠]|三角形|函数|方程", text or ""))
    )


def describe_visual(image_bytes: bytes, context: str) -> str:
    from .providers import get_provider

    return get_provider().describe_knowledge_image(image_bytes, context)
