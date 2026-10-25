"""读取教学资料中的文本；PDF 扫描页和疑似乱码页面会交给视觉模型识别。"""

import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import PurePosixPath

logger = logging.getLogger(__name__)

SUPPORTED_KNOWLEDGE_FORMATS = (
    ".pdf", ".docx", ".pptx", ".xlsx", ".xlsm",
    ".txt", ".md", ".csv", ".tsv", ".html", ".htm", ".json", ".xml", ".yaml", ".yml",
)


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


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16").replace("\x00", "").strip()
        except UnicodeDecodeError:
            pass
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            return data.decode(encoding).replace("\x00", "").strip()
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 后再导入。")


class _VisibleHtmlText(HTMLParser):
    _BLOCK_TAGS = {"address", "article", "br", "div", "footer", "h1", "h2", "h3", "h4",
                   "header", "li", "main", "ol", "p", "section", "table", "td", "th", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, _attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden_depth:
            self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"[ \t]+", " ", "".join(self.parts)).strip()


def _docx_text(data: bytes) -> str:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = Document(io.BytesIO(data))
    parts = []
    for block in document.element.body.iterchildren():
        if block.tag == qn("w:p"):
            text = Paragraph(block, document).text.strip()
            if text:
                parts.append(text)
        elif block.tag == qn("w:tbl"):
            table = Table(block, document)
            for row in table.rows:
                cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
    return "\n\n".join(parts).strip()


def _pptx_pages(data: bytes) -> tuple[list[tuple[None, str]], list[str]]:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(data))
    pages = []
    skipped = []
    for index, slide in enumerate(presentation.slides, start=1):
        parts = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = shape.text.strip()
                if text:
                    parts.append(text)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                    if any(cells):
                        parts.append(" | ".join(cells))
        text = "\n".join(parts).strip()
        if text:
            pages.append((None, f"幻灯片 {index}\n{text}"))
        else:
            skipped.append(str(index))
    warnings = ["以下幻灯片未提取到文字：" + "、".join(skipped) + "。"] if skipped else []
    return pages, warnings


def _xlsx_text(data: bytes) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    parts = []
    try:
        for sheet in workbook.worksheets:
            parts.append(f"工作表：{sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value).strip() for value in row]
                if any(values):
                    parts.append(" | ".join(values))
    finally:
        workbook.close()
    return "\n".join(parts).strip()


def _extract_non_pdf(data: bytes, extension: str) -> dict:
    warnings = []
    if extension == ".docx":
        try:
            text = _docx_text(data)
        except Exception as exc:
            raise ValueError("无法读取 Word 文档，请确认这是未损坏的 DOCX 文件。") from exc
        pages = [(None, text)] if text else []
    elif extension == ".pptx":
        try:
            pages, warnings = _pptx_pages(data)
        except Exception as exc:
            raise ValueError("无法读取 PowerPoint 文档，请确认这是未损坏的 PPTX 文件。") from exc
        text = "\n\n".join(page_text for _, page_text in pages)
    elif extension in {".xlsx", ".xlsm"}:
        try:
            text = _xlsx_text(data)
        except Exception as exc:
            raise ValueError("无法读取 Excel 文档，请确认这是未损坏的 XLSX/XLSM 文件。") from exc
        pages = [(None, text)] if text else []
    else:
        text = _decode_text(data)
        if extension in {".csv", ".tsv"}:
            delimiter = "\t" if extension == ".tsv" else ","
            try:
                rows = csv.reader(io.StringIO(text), delimiter=delimiter)
                text = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows).strip()
            except csv.Error as exc:
                raise ValueError("无法读取表格文本，请检查 CSV/TSV 文件格式。") from exc
        elif extension in {".html", ".htm"}:
            parser = _VisibleHtmlText()
            parser.feed(text)
            text = parser.text()
        elif extension == ".json":
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except json.JSONDecodeError as exc:
                raise ValueError("无法读取 JSON 文件，请检查文件格式。") from exc
        elif extension == ".xml":
            try:
                text = "\n".join(value.strip() for value in ET.fromstring(text).itertext() if value.strip())
            except ET.ParseError as exc:
                raise ValueError("无法读取 XML 文件，请检查文件格式。") from exc
        pages = [(None, text)] if text else []

    if not text.strip():
        raise ValueError("文件中没有提取到可检索的文字内容。")
    return {"pages": pages, "warnings": warnings}


def extract_knowledge_document(data: bytes, filename: str) -> dict:
    """按文件扩展名读取常见教学资料，统一交给学科 RAG 切分和索引。"""
    if not data:
        raise ValueError("资料文件不能为空。")
    extension = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    if extension not in SUPPORTED_KNOWLEDGE_FORMATS:
        supported = "、".join(SUPPORTED_KNOWLEDGE_FORMATS)
        raise ValueError(f"暂不支持此文件格式。支持：{supported}。")
    if extension == ".pdf":
        return extract_knowledge_pdf(data)
    return _extract_non_pdf(data, extension)
