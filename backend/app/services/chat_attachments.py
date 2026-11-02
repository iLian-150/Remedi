"""Small, bounded document extraction for chat attachments."""

from pathlib import PurePosixPath

from .knowledge_import import SUPPORTED_KNOWLEDGE_FORMATS, extract_knowledge_document

MAX_CHAT_ATTACHMENT_BYTES = 100 * 1024 * 1024
MAX_CHAT_ATTACHMENT_TEXT_CHARS = 40_000
CHAT_DOCUMENT_FORMATS = frozenset(SUPPORTED_KNOWLEDGE_FORMATS) - {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff",
}


def extract_chat_attachment(data: bytes, filename: str) -> dict:
    """Extract a bounded text context without retaining the uploaded original."""
    if not data:
        raise ValueError("文件内容为空，请重新选择文件。")
    if len(data) > MAX_CHAT_ATTACHMENT_BYTES:
        raise ValueError("文件不能超过 100MB。")

    name = PurePosixPath((filename or "").replace("\\", "/")).name or "附件"
    extension = PurePosixPath(name).suffix.lower()
    if extension not in CHAT_DOCUMENT_FORMATS:
        supported = "、".join(sorted(CHAT_DOCUMENT_FORMATS))
        raise ValueError(f"暂不支持此文件格式，请上传：{supported}。")

    extracted = extract_knowledge_document(data, name)
    pages = extracted.get("pages") or []
    parts = []
    for page_number, page_text in pages:
        text = str(page_text or "").strip()
        if not text:
            continue
        heading = f"[第 {page_number} 页]\n" if page_number else ""
        parts.append(heading + text)
    content = "\n\n".join(parts).strip()
    if not content:
        raise ValueError("文件中没有提取到可读取的文字内容。")

    truncated = len(content) > MAX_CHAT_ATTACHMENT_TEXT_CHARS
    if truncated:
        content = content[:MAX_CHAT_ATTACHMENT_TEXT_CHARS].rstrip() + "\n\n[文件内容较长，后续部分未附入对话]"
    return {"name": name[:255], "text": content, "truncated": truncated}
