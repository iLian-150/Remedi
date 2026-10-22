# 英语作文服务：提交 → Provider 评分 → 落库。
import json
from datetime import datetime
from typing import Dict

from ..models import Essay, Question, User
from .providers import get_provider


def score_and_save_essay(db, student: User, text: str,
                         question: Question = None, *, deferred: bool = False,
                         before_save=None) -> Dict:
    """Save an essay immediately scored or deferred until its assignment deadline."""
    result = (
        {"scores": {}, "grammar_issues": [], "overall": None}
        if deferred else get_provider().score_essay(
            text=text, prompt=question.stem if question else None,
        )
    )
    if before_save is not None:
        before_save()
    essay = Essay(
        student_id=student.id,
        question_id=question.id if question else None,
        text=text,
        scores_json=json.dumps(result["scores"], ensure_ascii=False),
        grammar_issues_json=json.dumps(result.get("grammar_issues", []), ensure_ascii=False),
        overall_comment=result.get("overall", ""),
        status="deferred" if deferred else "submitted",
    )
    db.add(essay)
    db.flush()
    out = present_essay(essay, with_text=False)
    db.commit()
    return out


def present_essay(essay: Essay, with_text: bool = False) -> Dict:
    scores = json.loads(essay.scores_json or "{}")
    score_fields = {"content", "structure", "grammar", "vocabulary", "expression", "total"}
    grammar_issues = json.loads(essay.grammar_issues_json or "[]")
    d = {
        "essay_id": essay.id,
        "question_id": essay.question_id,
        "status": essay.status or "submitted",
        "scores": scores if score_fields.issubset(scores) else None,
        "grammar_issues": grammar_issues if isinstance(grammar_issues, list) else [],
        "overall": essay.overall_comment,
        "submitted_at": essay.submitted_at,
    }
    if with_text:
        d["text"] = essay.text
    return d
