"""读取教学 PDF 文本；页码始终使用原 PDF 的物理页序。"""

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
        for index, page in enumerate(document):
            text = page.get_text("text", sort=True).replace("\x00", "").strip()
            if not text:
                skipped.append(index + 1)
                continue
            pages.append((index + 1, text))
        if not pages:
            raise ValueError("PDF 没有可提取的文字。扫描件请先完成 OCR，再导入带文字层的 PDF。")
        warnings = []
        if skipped:
            warnings.append("以下页未提取到文字，未进入检索库：" + "、".join(map(str, skipped)) + "。扫描页请先完成 OCR。")
        return {"pages": pages, "page_count": document.page_count,
                "indexed_pages": len(pages), "warnings": warnings}
