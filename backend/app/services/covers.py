# 练习册封面服务（v0.6.0 新增）：把 PDF 第一页渲染成封面图。
#
# 封面按文件名约定存放：UPLOAD_DIR/covers/{workbook_id}.jpg，不给 workbooks 表加列。
# 渲染失败（PDF 损坏、缺页、未装 pymupdf）一律静默返回 False，前端用纯色书脊兜底。
import logging
import os

from ..config import settings

logger = logging.getLogger(__name__)

_COVERS_SUBDIR = "covers"
_COVER_DPI = 150  # 约 150dpi：A4 首页约 1240x1754，足够书架展示与缩略图


def cover_file_path(workbook_id: int) -> str:
    return os.path.join(settings.UPLOAD_DIR, _COVERS_SUBDIR, f"{workbook_id}.jpg")


def cover_url(workbook_id: int) -> str | None:
    """封面图存在才给 URL，否则 None（前端走兜底书脊）。"""
    if os.path.isfile(cover_file_path(workbook_id)):
        return f"/api/uploads/{_COVERS_SUBDIR}/{workbook_id}.jpg"
    return None


def generate_cover(workbook_id: int, pdf_abs_path: str) -> bool:
    """渲染 PDF 第一页为封面 jpg；任何异常都吞掉并返回 False（静默跳过）。"""
    try:
        try:
            import pymupdf as fitz
        except ImportError:  # 老版本包名
            import fitz

        target = cover_file_path(workbook_id)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        doc = fitz.open(pdf_abs_path)
        try:
            if doc.page_count < 1:
                return False
            page = doc.load_page(0)
            zoom = _COVER_DPI / 72.0
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            pix.save(target)
        finally:
            doc.close()
        return os.path.isfile(target)
    except Exception as e:  # 未装 pymupdf / PDF 损坏等：封面是锦上添花，不阻塞主流程
        logger.info("练习册 %s 封面生成跳过：%s", workbook_id, e)
        return False


def ensure_cover(workbook_id: int, file_path: str) -> str | None:
    """封面缺失时懒生成一次（file_path 为相对 UPLOAD_DIR 的路径），返回最终 cover_url。"""
    url = cover_url(workbook_id)
    if url:
        return url
    pdf_abs = os.path.join(settings.UPLOAD_DIR, file_path)
    if os.path.isfile(pdf_abs):
        generate_cover(workbook_id, pdf_abs)
    return cover_url(workbook_id)
