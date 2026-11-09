"""只保存学生直接表达的回答风格，不从附件、题干或助手回复推断偏好。"""
import json
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import ChatSession, ChatSessionMessage, StudentAssistantPreference

STYLE_LABELS = {
    "concise": "喜欢简洁的回答，先给结论和关键步骤，避免冗长铺垫",
    "detailed": "喜欢详细的回答，展开解释原因和步骤",
    "guided": "喜欢引导式讲解，通过提问和分步提示帮助思考",
    "examples": "喜欢结合例子讲解",
}


def extract_styles(text: str) -> list[str] | None:
    text = text.strip()
    if re.fullmatch(r"(?:请)?(?:忘记|清除|删除|重置)(?:我(?:的)?)?(?:回答|回复|讲解)(?:风格)?偏好[。！!]?", text):
        return []
    if (len(text) > 160 or re.search(r'[\n\r`"“”「」？?]', text)
            or re.search(r"什么|哪种|是否|是不是|为什么|吗|例如|比如|如果|假如|题目|作答|附件|翻译|改写|他说|她说", text)):
        return None
    match = re.fullmatch(
        r"(?:我(?:更)?(?:喜欢|偏好)|我(?:希望|想要)(?:以后|今后|你以后|你今后)|"
        r"(?:请(?:你)?)?(?:以后|今后)(?:请)?|记住[，,:：]?我(?:喜欢|偏好))(.{1,100})", text,
    )
    if not match:
        return None
    body = match.group(1)
    if re.search(r"不喜欢|不想|不要|别|不需要|无需|不简|不详细", body) and "不要啰嗦" not in body:
        return None
    patterns = {
        "concise": r"简洁|简短|精简|简明|直接给结论|少说一点|不要啰嗦",
        "detailed": r"详细|详尽|细致|展开讲|讲透",
        "guided": r"引导|启发|多提问|一步一步",
        "examples": r"举例|例子",
    }
    positions = {key: max((m.start() for m in re.finditer(pattern, body)), default=-1)
                 for key, pattern in patterns.items()}
    if positions["concise"] >= 0 and positions["detailed"] >= 0:
        positions[min(("concise", "detailed"), key=positions.get)] = -1
    styles = [key for key, position in positions.items() if position >= 0]
    return styles or None


def preference_context(db: Session, student_id: int, current_text: str | None = None) -> str:
    from .chat_sessions import unpack_message_content

    # 首次并发访问也只创建一条记录；写锁/行锁保护增量游标和偏好更新。
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    db.execute(insert(StudentAssistantPreference).values(
        student_id=student_id, styles_json="[]", last_message_id=0,
    ).on_conflict_do_nothing(index_elements=["student_id"]))
    row = (db.query(StudentAssistantPreference).filter_by(student_id=student_id)
           .populate_existing().with_for_update().one())
    # 只读本人的用户消息；附件正文、助手回复和其他会话的题目上下文不作偏好来源。
    messages = (db.query(ChatSessionMessage)
                .join(ChatSession, ChatSession.id == ChatSessionMessage.session_id)
                .filter(ChatSession.user_id == student_id, ChatSessionMessage.role == "user",
                        ChatSessionMessage.id > row.last_message_id)
                .order_by(ChatSessionMessage.id.asc()).all())
    texts = [unpack_message_content(message.content)[0] for message in messages]
    if current_text is not None:
        texts.append(current_text)
    for text in texts:
        styles = extract_styles(text)
        if styles is not None:
            row.styles_json = json.dumps(styles)
            row.updated_at = datetime.now()
    if messages:
        row.last_message_id = messages[-1].id
    db.commit()
    styles = [style for style in json.loads(row.styles_json) if style in STYLE_LABELS]
    if not styles:
        return "尚未记录学生明确表达的回答风格偏好。不要声称已长期保存未记录的偏好。"
    return (
        "当前学生已明确表达并持久保存的回答偏好（跨对话适用）：\n"
        + "\n".join(f"- {STYLE_LABELS[style]}" for style in styles)
        + "\n在闲聊和学科讲解中都应用这些表达偏好；本轮明确要求优先。"
        "学生询问自己的回答偏好时，根据上述记录直接回答，不要说没有记录。"
    )
