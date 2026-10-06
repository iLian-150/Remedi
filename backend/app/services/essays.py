# 英语作文服务：提交 → Provider 评分 → 落库。
import json
from datetime import datetime
from typing import Dict

from ..models import Essay, Question, User
from .providers import get_provider


def score_and_save_essay(db, student: User, text: str,
                         question: Question = None) -> Dict:
    """调用 Provider 评分并落库，返回出参字典（含 essay_id）。"""
    provider = get_provider()
    result = provider.score_essay(text=text, prompt=question.stem if question else None)
    essay = Essay(
        student_id=student.id,
        question_id=question.id if question else None,
        text=text,
        scores_json=json.dumps(result["scores"], ensure_ascii=False),
        grammar_issues_json=json.dumps(result.get("grammar_issues", []), ensure_ascii=False),
        overall_comment=result.get("overall", ""),
    )
    db.add(essay)
    db.commit()
    db.refresh(essay)
    return present_essay(essay, with_text=False)


def present_essay(essay: Essay, with_text: bool = False) -> Dict:
    d = {
        "essay_id": essay.id,
        "question_id": essay.question_id,
        "scores": json.loads(essay.scores_json),
        "grammar_issues": json.loads(essay.grammar_issues_json),
        "overall": essay.overall_comment,
        "submitted_at": essay.submitted_at,
    }
    if with_text:
        d["text"] = essay.text
    return d
