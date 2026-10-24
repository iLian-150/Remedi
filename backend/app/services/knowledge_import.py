"""读取教学 PDF 文本；空白扫描页和疑似乱码页面会交给视觉模型识别。"""

import logging

logger = logging.getLogger(__name__)


def _looks_like_unusable_pdf_text(text: str) -> bool:
    """沿用 RAG 项目的质量判断，避免把明显乱码直接放入检索库。"""
    import re

    value = str(text or "").strip()
    if len(value) < 40:
        return False
    mojibake_chars = sum(1 for char in value if "\u00c0" <= char <= "\u00ff" or char == "�")
    if mojibake_chars / len(value) >= 0.03:
        return True
    tokens = [token for token in re.split(r"\s+", value) if token]
    if len(tokens) >= 30:
        single_char_tokens = sum(1 for token in tokens if len(token) == 1)
        average_token_length = sum(len(token) for token in tokens) / len(tokens)
        cjk_chars = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
        cjk_single_tokens = sum(
            1 for token in tokens
            if len(token) == 1 and "\u4e00" <= token <= "\u9fff"
        )
        if average_token_length <= 1.8 and single_char_tokens / len(tokens) >= 0.62:
            return True
        if cjk_chars >= 20 and cjk_single_tokens / cjk_chars >= 0.65:
            return True
    meaningful = sum(
        1 for char in value
        if "\u4e00" <= char <= "\u9fff" or char.isascii() and char.isalnum()
    )
    replacement = value.count("�") + value.count("?")
    return meaningful / len(value) < 0.35 or replacement / len(value) >= 0.08

def extract_knowledge_pdf(data: bytes) -> dict:
    import pymupdf

    if not data:
        raise ValueError("PDF 不能为空。")
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError("无法打开 PDF，请确认文件完整且格式正确。") from exc
    with document:
        if document.needs_pass:
            raise ValueError("请先解除 PDF 密码保护再导入。")
        if document.page_count < 1:
            raise ValueError("PDF 没有可读取的页面。")
        pages = []
        skipped = []
        failed = []
        repaired = []
        provider = None
        for index, page in enumerate(document):
            text = page.get_text("text", sort=True).replace("\x00", "").strip()
            needs_ocr = not text or _looks_like_unusable_pdf_text(text)
            if needs_ocr:
                try:
                    if provider is None:
                        from .providers import get_provider
                        provider = get_provider()
                    scale = 150 / 72
                    image_bytes = page.get_pixmap(
                        matrix=pymupdf.Matrix(scale, scale), alpha=False,
                    ).tobytes("png")
                    ocr_text = provider.extract_text_from_image(image_bytes, "image/png")
                except Exception as exc:
                    logger.warning(
                        "PDF 第 %s 页 OCR 失败（%s）", index + 1, type(exc).__name__,
                    )
                    failed.append(index + 1)
                else:
                    if ocr_text:
                        text = ocr_text
                        repaired.append(index + 1)
                    elif not text:
                        skipped.append(index + 1)
                    else:
                        failed.append(index + 1)
            if not text:
                if index + 1 not in skipped:
                    skipped.append(index + 1)
                continue
            pages.append((index + 1, text))
        if not pages:
            if failed:
                raise RuntimeError("扫描页文字识别服务暂不可用，请稍后重试。")
            raise ValueError("PDF 页面中没有识别到可用文字，请检查扫描清晰度后重试。")
        warnings = []
        if skipped:
            warnings.append("以下页未能识别到文字，未进入检索库：" + "、".join(map(str, skipped)) + "。")
        if failed:
            warnings.append("以下页的 OCR 暂未成功：" + "、".join(map(str, failed)) + "。")
        if repaired:
            warnings.append("已对以下扫描或疑似乱码页面进行 OCR：" + "、".join(map(str, repaired)) + "。")
        return {"pages": pages, "page_count": document.page_count,
                "indexed_pages": len(pages), "ocr_pages": len(repaired),
                "warnings": warnings}
