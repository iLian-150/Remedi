"""Shared cleanup for upload files referenced by multiple Remedi features."""
import logging
import os
from typing import Iterable

from sqlalchemy import select, union_all
from sqlalchemy.orm import Session

from ..config import settings

logger = logging.getLogger(__name__)


def delete_unreferenced_uploads(
    db: Session,
    file_paths: Iterable[str],
    *,
    reason: str,
) -> None:
    """Remove upload files only after every supported database reference is gone."""
    upload_dir = os.path.realpath(settings.UPLOAD_DIR)
    safe_paths = {}
    for stored_path in file_paths:
        if not stored_path:
            continue
        absolute_path = os.path.realpath(
            stored_path if os.path.isabs(stored_path)
            else os.path.join(upload_dir, stored_path)
        )
        try:
            inside_upload_dir = os.path.commonpath(
                (upload_dir, absolute_path)
            ) == upload_dir
        except ValueError:
            inside_upload_dir = False
        if absolute_path == upload_dir or not inside_upload_dir:
            continue
        safe_paths[stored_path] = absolute_path

    if not safe_paths:
        return

    # Callers may have just rolled back a failed write or committed a deletion.
    db.rollback()
    from ..models import (
        ChatSessionMessageImage,
        StudentQuestionCapture,
        SubmissionImage,
        Workbook,
    )

    reference_columns = (
        ChatSessionMessageImage.file_path,
        SubmissionImage.file_path,
        StudentQuestionCapture.image_path,
        Workbook.file_path,
    )
    referenced_paths = set()
    paths = list(safe_paths)
    try:
        for start in range(0, len(paths), 200):
            path_chunk = paths[start:start + 200]
            reference_queries = [
                select(column.label("file_path")).where(column.in_(path_chunk))
                for column in reference_columns
            ]
            referenced_paths.update(
                path
                for (path,) in db.execute(union_all(*reference_queries)).all()
                if path
            )
    except Exception:
        db.rollback()
        logger.warning(
            "%s检查图片引用失败，保留原图",
            reason,
            exc_info=True,
        )
        return

    for stored_path, absolute_path in safe_paths.items():
        if stored_path in referenced_paths:
            continue
        try:
            os.remove(absolute_path)
        except FileNotFoundError:
            continue
        except Exception:
            db.rollback()
            logger.warning(
                "%s清理图片失败（file_path=%s）",
                reason,
                stored_path,
                exc_info=True,
            )
