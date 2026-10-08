# 练习册按页提题（v0.13.0）：老师发布线下作业时填页码范围，点「从 PDF 自动识别」
# → 本服务把指定页渲染成图，逐页调 Provider 的视觉提取，汇成草稿题列表。
#
# 分工要说清：页码解析与页面渲染是纯程序处理（不用 AI，pymupdf 渲染）；
# 「从页面图里把题目一道道拆出来」走视觉大模型（Provider.extract_questions_from_page）。
# 产出永远是草稿：前端填入题目卡后，必须由教师检查修改才能发布，与拍照识别同口径。
import logging
import os
import re
from typing import Dict, List

from ..config import settings
from .providers import get_provider

logger = logging.getLogger(__name__)

MAX_PAGES = 8        # 一次最多识别的页数：防误填大范围把视觉模型额度烧穿
_RENDER_DPI = 200    # 页面渲染分辨率：题目文字要够清，又不能让图片大到传输超时

# 只认带「页」的段（如 第12页 / 第 12-14 页），避免把「第 1-8 题」的题号当页码
_PAGE_RE = re.compile(r"第?\s*(\d+)\s*(?:[-~—–至到]\s*(\d+)\s*)?页")
# 题号段只作提示，喂给视觉模型帮它定位（如 第 1-8 题）
_QUESTION_RE = re.compile(r"第?\s*(\d+)\s*(?:[-~—–至到]\s*(\d+)\s*)?题")


def parse_pages(text: str, page_count: int) -> List[int]:
    """从自由文本页码里解析 1-based 页号列表（去重、排序、按 PDF 实际页数夹紧）。

    解析不到 / 超过单次上限 → ValueError（信息可直接给老师看，路由转 400）。"""
    pages: List[int] = []
    for m in _PAGE_RE.finditer(text or ""):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if b < a:
            a, b = b, a
        pages.extend(range(a, b + 1))
    if not pages:
        # 兜底：没有任何「页」字时，取文本里的第一个数字段当页码（如直接填 12-14）
        m = re.search(r"(\d+)\s*(?:[-~—–至到]\s*(\d+))?", text or "")
        if m:
            a = int(m.group(1))
            b = int(m.group(2)) if m.group(2) else a
            if b < a:
                a, b = b, a
            pages = list(range(a, b + 1))
    pages = sorted({p for p in pages if 1 <= p <= page_count})
    if not pages:
        raise ValueError("没能从页码范围里读出有效页码，请写成「第 12-14 页」这样的格式。")
    if len(pages) > MAX_PAGES:
        raise ValueError(
            f"一次最多识别 {MAX_PAGES} 页（这次有 {len(pages)} 页），请把范围拆小一点、分两次识别。"
        )
    return pages


def question_hint(text: str) -> str:
    """题号范围 → 给视觉模型的定位提示；没有就不给。"""
    m = _QUESTION_RE.search(text or "")
    if not m:
        return ""
    if m.group(2):
        return f"本页范围内的习题大约是第 {m.group(1)} 到第 {m.group(2)} 题"
    return f"本页范围大约从第 {m.group(1)} 题开始"


def extract_questions_from_workbook(file_path_rel: str, page_range_text: str) -> Dict:
    """主入口：打开 PDF → 解析页码 → 逐页渲染并提取 → {pages, questions, warnings}。

    单页提取失败不拖垮整批：该页记一条 warning，其余页照常返回。"""
    abs_path = os.path.join(settings.UPLOAD_DIR, file_path_rel)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError("练习册 PDF 文件不存在了，请先重新上传这本练习册。")
    try:
        import pymupdf as fitz
    except ImportError:  # 老版本包名
        import fitz

    doc = fitz.open(abs_path)
    try:
        pages = parse_pages(page_range_text, doc.page_count)
        hint = question_hint(page_range_text)
        provider = get_provider()
        questions: List[Dict] = []
        warnings: List[str] = []
        zoom = _RENDER_DPI / 72.0
        for pno in pages:
            page = doc.load_page(pno - 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            image_bytes = pix.tobytes("jpeg")
            try:
                found = provider.extract_questions_from_page(image_bytes, "image/jpeg", hint)
            except Exception as e:  # Provider 层已自带降级，这里只防万一
                logger.warning("第 %s 页提题异常：%s", pno, e)
                found = []
            if not found:
                warnings.append(
                    f"第 {pno} 页没有识别到题目，可以对着这一页用下方「拍照上传题目页」补录。"
                )
            for item in found:
                prompt = str(item.get("prompt", "")).strip()
                if not prompt:
                    continue
                questions.append({
                    "prompt": prompt,
                    "knowledge_point": str(item.get("knowledge_point", "")).strip(),
                    "source_page": pno,
                })
        return {"pages": pages, "questions": questions, "warnings": warnings}
    finally:
        doc.close()
