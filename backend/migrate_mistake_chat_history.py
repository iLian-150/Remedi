"""Move legacy mistake-book prompts out of student chat sessions.

Run once after deploying the dedicated student-mistake chat table. Only an
exact legacy prompt tied to one uniquely owned mistake is moved; ambiguous
messages stay in place for review instead of risking unrelated chat history.
"""
import re

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    ChatSession,
    ChatSessionMessage,
    ChatSessionMessageImage,
    ChatSessionMessageMistakeLink,
    Error,
    Question,
    Step,
    StudentMistakeChatMessage,
    StudentQuestionCapture,
    Submission,
)
from app.routers.student import _mistake_category

PREFIX = "请围绕这道错题回答学生的问题。学科："
SUBJECT_NAMES = {
    "math": "数学", "english": "英语", "physics": "物理",
    "chemistry": "化学", "chinese": "语文", "biology": "生物",
    "politics": "政治", "history": "历史", "geography": "地理",
}


def parse_prompt(content: str):
    subject_match = re.match(re.escape(PREFIX) + r"([^。]+)。。?\n", content)
    question_marker = "\n题目："
    question_start = content.find(question_marker)
    student_question_marker = "\n学生问题："
    student_question_start = content.rfind(student_question_marker)
    if not subject_match or question_start < 0 or student_question_start < question_start:
        return None

    subject = subject_match.group(1)
    knowledge_line = content[subject_match.end():content.find("\n", subject_match.end())]
    knowledge_match = re.fullmatch(r"知识点：(.*)；错误类别：(.*)\。?", knowledge_line)
    if not knowledge_match:
        return None

    text_start = question_start + len(question_marker)
    delimiters = [position for label in ("\n学生作答：", "\n诊断说明：", student_question_marker)
                  if (position := content.find(label, text_start)) >= 0]
    text_end = min(delimiters, default=student_question_start)
    stem = content[text_start:text_end]
    step_text = None
    step_start = content.find("\n学生作答：", text_end)
    if step_start >= 0:
        step_start += len("\n学生作答：")
        step_end = min((position for label in ("\n诊断说明：", student_question_marker)
                        if (position := content.find(label, step_start)) >= 0),
                       default=student_question_start)
        step_text = content[step_start:step_end]

    return {
        "subject": subject,
        "knowledge_point": knowledge_match.group(1),
        "category_label": knowledge_match.group(2),
        "stem": stem,
        "step_text": step_text,
        "question": content[student_question_start + len(student_question_marker):],
    }


def matching_mistakes(db: Session, student_id: int, parsed: dict) -> list[int]:
    candidates = (db.query(Error, Question, Step)
                 .join(Submission, Error.submission_id == Submission.id)
                 .join(Question, Submission.question_id == Question.id)
                 .outerjoin(Step, Error.step_id == Step.id)
                 .filter(Submission.student_id == student_id,
                         Question.stem == parsed["stem"])
                 .all())
    matches = []
    for error, question, step in candidates:
        category_label = _mistake_category(
            question.subject, error.error_type, error.knowledge_point,
        )[1]
        if (SUBJECT_NAMES.get(question.subject, question.subject or "其他学科") != parsed["subject"]
                or (error.knowledge_point or "") != parsed["knowledge_point"]
                or category_label != parsed["category_label"]
                or ((step.text or None) if step else None) != parsed["step_text"]):
            continue
        matches.append(error.id)

    if matches:
        return matches

    if parsed["category_label"] != "自主收录" or parsed["step_text"] is not None:
        return []
    captures = db.query(StudentQuestionCapture).filter(
        StudentQuestionCapture.student_id == student_id,
        StudentQuestionCapture.saved_at.isnot(None),
        StudentQuestionCapture.question_text == parsed["stem"],
    ).all()
    return [
        -capture.id for capture in captures
        if SUBJECT_NAMES.get(capture.subject, capture.subject or "其他学科") == parsed["subject"]
        and parsed["knowledge_point"] == "自主复习"
    ]


def migrate(db: Session) -> tuple[int, int]:
    prompts = (db.query(ChatSessionMessage, ChatSession)
               .join(ChatSession, ChatSession.id == ChatSessionMessage.session_id)
               .filter(ChatSessionMessage.role == "user",
                       ChatSessionMessage.content.startswith(PREFIX))
               .order_by(ChatSessionMessage.id.asc()).all())
    moved = skipped = 0
    affected_session_ids = set()

    try:
        for prompt, session in prompts:
            parsed = parse_prompt(prompt.content)
            if not parsed or not parsed["question"].strip():
                skipped += 1
                continue
            matches = matching_mistakes(db, session.user_id, parsed)
            if len(matches) != 1:
                skipped += 1
                continue

            assistant = (db.query(ChatSessionMessage)
                         .filter(ChatSessionMessage.session_id == session.id,
                                 ChatSessionMessage.id > prompt.id)
                         .order_by(ChatSessionMessage.id.asc()).first())
            if assistant is not None and assistant.role != "assistant":
                assistant = None

            db.add(StudentMistakeChatMessage(
                student_id=session.user_id, mistake_id=matches[0], role="user",
                content=parsed["question"], created_at=prompt.created_at,
            ))
            if assistant is not None:
                db.add(StudentMistakeChatMessage(
                    student_id=session.user_id, mistake_id=matches[0], role="assistant",
                    content=assistant.content, created_at=assistant.created_at,
                ))
                db.query(ChatSessionMessageMistakeLink).filter_by(message_id=assistant.id).delete()
                db.query(ChatSessionMessageImage).filter_by(message_id=assistant.id).delete()
                db.delete(assistant)
            db.query(ChatSessionMessageImage).filter_by(message_id=prompt.id).delete()
            db.delete(prompt)
            affected_session_ids.add(session.id)
            moved += 1

        db.flush()
        for session in db.query(ChatSession).filter(
            ChatSession.id.in_(affected_session_ids),
        ).all():
            remaining = (db.query(ChatSessionMessage)
                         .filter_by(session_id=session.id)
                         .order_by(ChatSessionMessage.id.asc()).all())
            session.message_count = len(remaining)
            session.updated_at = remaining[-1].created_at if remaining else session.created_at
            first_user_message = next((row.content for row in remaining if row.role == "user"), None)
            if first_user_message:
                session.title = first_user_message[:20].strip() or "新对话"
            else:
                session.title = "新对话"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return moved, skipped


def main():
    with SessionLocal() as db:
        moved, skipped = migrate(db)
    print(f"已迁移 {moved} 组错题问答，跳过 {skipped} 条无法唯一匹配的消息。")


if __name__ == "__main__":
    main()
