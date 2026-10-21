# 教师复核流：整份作业结算后，百分制总分低于 60 分才进入教师队列。
# 学生立即查看系统评分、错题和订正任务；教师可改判并同步最终分。
#
# 学生的学习报告/画像可以选择排除 pending 记录；错题本与订正待办不排除。
from datetime import datetime
from decimal import Decimal
import math
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy import case, func, or_, tuple_
from sqlalchemy.orm import Session, joinedload, load_only

from ..models import (
    Assignment,
    AssignmentExt,
    AssignmentScoring,
    Error,
    Notification,
    Question,
    Step,
    Submission,
    SubmissionReview,
    User,
)
from .confidence import normalize_confidence

PENDING = "pending"
APPROVED = "approved"
REVIEW_THRESHOLD = 0.60  # 作业最终得分率阈值；不用于单题或模型置信度


def low_error_confidence_predicate():
    """SQL predicate matching review_reasons' finite, below-threshold check."""
    return or_(
        Error.confidence < REVIEW_THRESHOLD,
        Error.confidence == math.inf,
        Error.confidence == math.nan,
        Error.confidence != Error.confidence,
    )


def create_pending_review(db: Session, submission: Submission) -> SubmissionReview:
    """实时批改入口产生新提交后调用：建一条 pending 审核行（幂等，已有行不覆盖）。"""
    return create_pending_reviews(db, [submission])[submission.id]


def create_pending_reviews(
    db: Session,
    submissions: Iterable[Submission],
    *,
    existing_rows: Optional[Iterable[SubmissionReview]] = None,
    commit: bool = True,
) -> dict[int, SubmissionReview]:
    """幂等地为多条提交建待审行；commit=False 时由调用方负责提交。"""
    unique_submissions = {item.id: item for item in submissions if item.id is not None}
    if not unique_submissions:
        return {}

    if existing_rows is None:
        existing_rows = []
        submission_ids = list(unique_submissions)
        for start in range(0, len(submission_ids), 500):
            existing_rows.extend(
                db.query(SubmissionReview).filter(
                    SubmissionReview.submission_id.in_(submission_ids[start:start + 500])
                ).all()
            )
    rows_by_id = {row.submission_id: row for row in existing_rows}
    added = False
    for submission_id in unique_submissions:
        if submission_id not in rows_by_id:
            row = SubmissionReview(submission_id=submission_id, status=PENDING)
            db.add(row)
            rows_by_id[submission_id] = row
            added = True
    if added and commit:
        db.commit()
    return rows_by_id


def visual_confidence_signals(image_confidence, visual_steps) -> List[float]:
    """提取视觉模型的整图与逐步判断置信度，供审核阈值共用。"""
    raw_values = [image_confidence]
    for step in visual_steps or []:
        if isinstance(step, dict) and str(step.get("text", "")).strip():
            # 与 diagnose_visual_submission 一致：缺少步骤置信度时按 0.5 处理。
            raw_values.append(step.get("confidence", 0.5))

    return [normalize_confidence(raw) for raw in raw_values]


def _step_counts_by_submission(
    db: Session, submission_ids: Iterable[int],
) -> dict[int, Tuple[int, int]]:
    """分块按提交聚合有效步骤数，避免全量回传步骤状态或超过数据库参数上限。"""
    ids = list(dict.fromkeys(submission_ids))
    counts_by_submission = {}
    for start in range(0, len(ids), 500):
        rows = db.query(
            Step.submission_id,
            func.sum(case((Step.status == "ok", 1), else_=0)),
            func.count(Step.id),
        ).filter(
            Step.submission_id.in_(ids[start:start + 500]),
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).group_by(Step.submission_id).all()
        counts_by_submission.update({
            submission_id: (int(correct or 0), int(total or 0))
            for submission_id, correct, total in rows
        })
    return counts_by_submission


def assignment_accuracy_context(
    db: Session, submission: Submission
) -> Optional[Tuple[List[Submission], int, int]]:
    """返回同一学生、整份作业各题最新提交的步骤正确率统计。

    正确率只统计已判定（正确、错误或无法解析）的作答步骤；跳过步骤和未提交题目
    不进入分母。
    """
    question = submission.question or db.query(Question).filter(
        Question.id == submission.question_id
    ).first()
    if question is None:
        return None

    latest_ranked = (
        db.query(
            Submission.id.label("submission_id"),
            func.row_number().over(
                partition_by=Submission.question_id,
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        )
        .join(Question, Question.id == Submission.question_id)
        .filter(
            Submission.student_id == submission.student_id,
            Question.assignment_id == question.assignment_id,
            Submission.status == "graded",
        )
        .subquery()
    )
    latest_submissions = (
        db.query(Submission)
        .join(latest_ranked, latest_ranked.c.submission_id == Submission.id)
        .filter(latest_ranked.c.rank == 1)
        .order_by(Submission.question_id.asc())
        .all()
    )
    step_counts = _step_counts_by_submission(
        db, (item.id for item in latest_submissions)
    )
    correct = sum(counts[0] for counts in step_counts.values())
    total = sum(counts[1] for counts in step_counts.values())
    return latest_submissions, correct, total


def assignment_accuracy_contexts(
    db: Session, submissions: Iterable[Submission]
) -> dict[tuple[int, int], Optional[Tuple[List[Submission], int, int]]]:
    """批量计算待审核列表中各学生、各作业的已批改步骤正确率。"""
    requested = {}
    for submission in submissions:
        question = submission.question
        if question is not None:
            requested[(submission.student_id, question.assignment_id)] = None
    if not requested:
        return requested

    latest_submissions_by_key = {key: [] for key in requested}
    requested_keys = list(requested)
    # SQLite 默认绑定参数上限通常为 999；每个键有两个参数，按 400 对分块。
    # 在数据库中按学生、题目对历史提交排序，只把每题最新的已批改提交传回，
    # 避免待审核队列随重做历史增长而反复物化所有旧提交。
    for start in range(0, len(requested_keys), 400):
        key_chunk = requested_keys[start:start + 400]
        latest_ranked = (
            db.query(
                Submission.id.label("submission_id"),
                Submission.student_id.label("student_id"),
                Question.assignment_id.label("assignment_id"),
                func.row_number().over(
                    partition_by=(Submission.student_id, Submission.question_id),
                    order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
                ).label("rank"),
            )
            .join(Question, Question.id == Submission.question_id)
            .filter(
                tuple_(Submission.student_id, Question.assignment_id).in_(key_chunk),
                Submission.status == "graded",
            )
            .subquery()
        )
        candidate_rows = (
            db.query(Submission, latest_ranked.c.assignment_id)
            .join(latest_ranked, latest_ranked.c.submission_id == Submission.id)
            .filter(latest_ranked.c.rank == 1)
            .order_by(Submission.submitted_at.asc(), Submission.id.asc())
            .all()
        )
        for submission, assignment_id in candidate_rows:
            key = (submission.student_id, assignment_id)
            latest_submissions_by_key[key].append(submission)
    latest_ids = {
        submission.id
        for rows in latest_submissions_by_key.values()
        for submission in rows
    }
    statuses_by_submission = _step_counts_by_submission(db, latest_ids)

    for key, latest_submissions in latest_submissions_by_key.items():
        correct = total = 0
        for submission in latest_submissions:
            submission_counts = statuses_by_submission.get(submission.id, (0, 0))
            correct += submission_counts[0]
            total += submission_counts[1]
        requested[key] = (latest_submissions, correct, total)
    return requested


def assignment_score_contexts(
    db: Session,
    submissions: Iterable[Submission],
    *,
    force_complete_keys: Optional[Set[Tuple[int, int]]] = None,
) -> dict[tuple[int, int], dict]:
    """按学生和作业汇总每题最新 AI 分；只有全题已批改或截止结算时才定审核。"""
    requested = {}
    for submission in submissions:
        question = submission.question
        if question is not None:
            requested[(submission.student_id, question.assignment_id)] = []
    if not requested:
        return {}

    force_complete_keys = force_complete_keys or set()
    keys = list(requested)
    for start in range(0, len(keys), 400):
        key_chunk = keys[start:start + 400]
        latest_ranked = (
            db.query(
                Submission.id.label("submission_id"),
                Question.assignment_id.label("assignment_id"),
                func.row_number().over(
                    partition_by=(Submission.student_id, Submission.question_id),
                    order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
                ).label("rank"),
            )
            .join(Question, Question.id == Submission.question_id)
            .join(Assignment, Assignment.id == Question.assignment_id)
            .outerjoin(User, User.id == Assignment.created_by)
            .filter(
                tuple_(Submission.student_id, Question.assignment_id).in_(key_chunk),
                Submission.status == "graded",
                or_(Assignment.created_by.is_(None), User.role != "student"),
            )
            .subquery()
        )
        rows = (
            db.query(Submission, latest_ranked.c.assignment_id)
            .join(latest_ranked, latest_ranked.c.submission_id == Submission.id)
            .options(joinedload(Submission.question))
            .filter(latest_ranked.c.rank == 1)
            .all()
        )
        for submission, assignment_id in rows:
            requested[(submission.student_id, assignment_id)].append(submission)

    assignment_ids = {assignment_id for _, assignment_id in keys}
    question_counts = dict(db.query(
        Question.assignment_id, func.count(Question.id)
    ).filter(
        Question.assignment_id.in_(assignment_ids)
    ).group_by(Question.assignment_id).all())

    totals = dict(db.query(
        AssignmentScoring.assignment_id,
        AssignmentScoring.total_score,
    ).filter(
        AssignmentScoring.assignment_id.in_(assignment_ids)
    ).all())
    from . import scoring as scoring_svc

    all_latest = [item for rows in requested.values() for item in rows]
    score_by_submission = {}
    for start in range(0, len(all_latest), 300):
        score_by_submission.update(scoring_svc.visible_scores(
            db, all_latest[start:start + 300], commit=False
        ))

    now = datetime.now()
    due_assignment_ids = {
        row[0] for row in db.query(AssignmentExt.assignment_id).filter(
            AssignmentExt.deadline.isnot(None), AssignmentExt.deadline <= now,
        ).filter(AssignmentExt.assignment_id.in_(assignment_ids)).all()
    }
    result = {}
    for key, latest in requested.items():
        _student_id, assignment_id = key
        question_count = int(question_counts.get(assignment_id, 0))
        configured_total = totals.get(assignment_id)
        max_score = Decimal(str(configured_total or scoring_svc.DEFAULT_TOTAL))
        earned_score = sum((
            Decimal(str(score_by_submission[item.id]["score"]))
            for item in latest if item.id in score_by_submission
        ), Decimal("0"))
        completed = question_count > 0 and len(latest) >= question_count
        forced = key in force_complete_keys or assignment_id in due_assignment_ids
        result[key] = {
            "latest_submissions": latest,
            "score": earned_score,
            "max_score": max_score,
            "percent": earned_score / max_score * Decimal("100") if max_score > 0 else Decimal("0"),
            "complete": completed or forced,
            "all_questions_answered": completed,
        }
    return result


def _release_assignment_reviews(
    db: Session, student_id: int, assignment_id: int,
) -> None:
    """移除旧规则产生的待审状态，不伪装成教师手动审核。"""
    rows = db.query(SubmissionReview).join(
        Submission, Submission.id == SubmissionReview.submission_id,
    ).join(
        Question, Question.id == Submission.question_id,
    ).filter(
        Submission.student_id == student_id,
        Question.assignment_id == assignment_id,
        SubmissionReview.status == PENDING,
    ).all()
    for row in rows:
        row.status = APPROVED
        row.reviewed_by = None
        row.reviewed_at = datetime.now()


def refresh_assignment_review(
    db: Session,
    submission: Submission,
    *,
    force_complete: bool = False,
    commit: bool = True,
) -> Optional[SubmissionReview]:
    """按当前作业最新提交重算审核状态；可由截止批改强制定为已结算。"""
    question = submission.question or db.query(Question).filter(
        Question.id == submission.question_id
    ).first()
    if question is None:
        return None
    key = (submission.student_id, question.assignment_id)
    def refresh_memory():
        from .learning_memory import refresh_student_learning_memory
        return refresh_student_learning_memory(
            db, submission.student_id, subject=question.subject,
            knowledge_point=question.knowledge_point, commit=False,
        )

    context = assignment_score_contexts(
        db,
        [submission],
        force_complete_keys={key} if force_complete else set(),
    ).get(key)
    if not context:
        refresh_memory()
        if commit:
            db.commit()
        return None
    if not context["complete"] or context["percent"] >= Decimal("60"):
        _release_assignment_reviews(db, *key)
        refresh_memory()
        if commit:
            db.commit()
        return None
    rows_by_id = create_pending_reviews(
        db, context["latest_submissions"], commit=False,
    )
    refresh_memory()
    if commit:
        db.commit()
    return rows_by_id.get(submission.id)


def review_reasons(
    db: Session,
    submission: Submission,
    confidence_signals: Iterable[float] = (),
    *,
    assignment_context: Optional[Tuple[List[Submission], int, int]] = None,
    step_statuses: Optional[Iterable[str]] = None,
    step_counts: Optional[Tuple[int, int]] = None,
    error_confidences: Optional[Iterable[float]] = None,
    has_low_error_confidence: Optional[bool] = None,
) -> List[str]:
    """教师审核只由结算后的整份作业百分制得分严格低于 60 触发。"""
    question = submission.question or db.query(Question).filter(
        Question.id == submission.question_id
    ).first()
    if question is None:
        return []
    context = assignment_score_contexts(db, [submission]).get(
        (submission.student_id, question.assignment_id)
    )
    if not context or not context["complete"] or context["percent"] >= Decimal("60"):
        return []
    return [
        f"整份作业得分低于 60 分（{context['score']}/{context['max_score']} 分）"
    ]


def needs_teacher_review(db: Session, submission: Submission,
                         confidence_signals: Iterable[float] = (), *,
                         assignment_context: Optional[Tuple[List[Submission], int, int]] = None) -> bool:
    """完成整份作业结算后，仅在百分制得分低于 60 分时送审。"""
    return bool(review_reasons(
        db, submission, confidence_signals, assignment_context=assignment_context
    ))


def create_review_if_needed(
    db: Session,
    submission: Submission,
    confidence_signals: Iterable[float] = (),
    *,
    commit: bool = True,
) -> Optional[SubmissionReview]:
    """结算整份作业后按百分制得分决定审核；错题诊断和订正不受审核阻塞。"""
    return refresh_assignment_review(db, submission, commit=commit)


def backfill_missing_review_records(db: Session) -> int:
    """按新规则回填低分待审作业，并清理由旧阈值产生的其他待审状态。"""
    latest_graded = (
        db.query(
            Submission.id.label("submission_id"),
            Submission.student_id.label("student_id"),
            Question.assignment_id.label("assignment_id"),
            func.row_number().over(
                partition_by=(Submission.student_id, Submission.question_id),
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        )
        .join(Question, Question.id == Submission.question_id)
        .filter(Submission.status == "graded")
        .subquery()
    )
    latest_submissions = (
        db.query(Submission)
        .join(latest_graded, latest_graded.c.submission_id == Submission.id)
        .options(joinedload(Submission.question))
        .filter(latest_graded.c.rank == 1)
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    if not latest_submissions:
        return 0

    now = datetime.now()
    due_ids = {
        row[0] for row in db.query(AssignmentExt.assignment_id).filter(
            AssignmentExt.assignment_id.in_({
                sub.question.assignment_id for sub in latest_submissions
                if sub.question is not None
            }),
            AssignmentExt.deadline.isnot(None),
            AssignmentExt.deadline <= now,
        ).all()
    }
    force_keys = {
        (sub.student_id, sub.question.assignment_id)
        for sub in latest_submissions
        if sub.question is not None and sub.question.assignment_id in due_ids
    }
    contexts = assignment_score_contexts(
        db, latest_submissions, force_complete_keys=force_keys,
    )
    target_ids = set()
    for context in contexts.values():
        if context["complete"] and context["percent"] < Decimal("60"):
            target_ids.update(item.id for item in context["latest_submissions"])

    existing_rows = db.query(SubmissionReview).all()
    rows_by_id = {row.submission_id: row for row in existing_rows}
    latest_ids = {sub.id for sub in latest_submissions}
    for row in existing_rows:
        if row.status == PENDING and row.submission_id not in target_ids:
            row.status = APPROVED
            row.reviewed_by = None
            row.reviewed_at = now

    added = 0
    for submission_id in target_ids:
        row = rows_by_id.get(submission_id)
        if row is None:
            db.add(SubmissionReview(submission_id=submission_id, status=PENDING))
            added += 1
    db.commit()
    return added


def review_status(db: Session, submission_id: int) -> str:
    """单条提交的审核状态：无审核行 = approved（历史/种子数据口径）。"""
    row = db.query(SubmissionReview).filter(
        SubmissionReview.submission_id == submission_id
    ).first()
    if row is None:
        return APPROVED
    return row.status


def review_status_map(db: Session, submission_ids: Iterable[int]) -> dict:
    """批量查审核状态，返回 {submission_id: status}，无行的不出现在 dict 里。"""
    ids = list(submission_ids)
    if not ids:
        return {}
    statuses = {}
    for start in range(0, len(ids), 500):
        for submission_id, status in db.query(
            SubmissionReview.submission_id, SubmissionReview.status
        ).filter(
            SubmissionReview.submission_id.in_(ids[start:start + 500])
        ).all():
            statuses[submission_id] = status
    return statuses


def pending_submission_ids(db: Session, student_id: Optional[int] = None) -> Set[int]:
    """全部（或某个学生的）待审核提交 id 集合，供分数/统计等口径筛选。"""
    query = (
        db.query(SubmissionReview.submission_id)
        .filter(SubmissionReview.status == PENDING)
    )
    if student_id is not None:
        query = query.join(
            Submission, Submission.id == SubmissionReview.submission_id
        ).filter(Submission.student_id == student_id)
    return {row[0] for row in query.all()}


def visible_submissions(db: Session, submissions: List[Submission]) -> List[Submission]:
    """从提交列表中滤掉待审核的（学生侧统计/报告/画像共用）。"""
    if not submissions:
        return submissions
    pending = pending_submission_ids(db, submissions[0].student_id)
    return [s for s in submissions if s.id not in pending]


def approve_submission(db: Session, submission: Submission, teacher,
                       *, notify: bool = True,
                       commit: bool = True) -> SubmissionReview:
    """把一条提交置为 approved 并给学生发审核通过提醒（幂等：
    已 approved 的不重复发提醒）。返回审核行。"""
    row = db.query(SubmissionReview).filter(
        SubmissionReview.submission_id == submission.id
    ).first()
    if row is None:
        row = SubmissionReview(submission_id=submission.id)
        db.add(row)
    was_pending = row.status == PENDING
    row.status = APPROVED
    row.reviewed_by = teacher.id
    row.reviewed_at = datetime.now()
    if notify and was_pending:
        title = ""
        if submission.question is not None:
            assignment = submission.question.assignment
            title = assignment.title if assignment else ""
        db.add(Notification(
            user_id=submission.student_id,
            type="review_approved",
            content=(
                f"{teacher.name}已审核通过你《{title}》的批改结果，"
                "去看看老师的诊断吧。"
            ),
            related_submission_id=submission.id,
        ))
    if commit:
        expire_on_commit = db.expire_on_commit
        db.expire_on_commit = False
        try:
            db.commit()
        finally:
            db.expire_on_commit = expire_on_commit
    return row


def approve_submissions(db: Session, submissions: Iterable[Submission], teacher) -> None:
    """批量更新审核状态并添加提醒；由调用方统一提交事务。"""
    unique_submissions = {
        submission.id: submission
        for submission in submissions
        if submission.id is not None
    }
    if not unique_submissions:
        return

    submission_ids = list(unique_submissions)
    rows_by_id = {}
    for start in range(0, len(submission_ids), 500):
        rows_by_id.update({
            row.submission_id: row
            for row in db.query(SubmissionReview).filter(
                SubmissionReview.submission_id.in_(submission_ids[start:start + 500])
            ).all()
        })

    for submission_id, submission in unique_submissions.items():
        row = rows_by_id.get(submission_id)
        if row is None:
            row = SubmissionReview(submission_id=submission_id)
            db.add(row)
        was_pending = row.status == PENDING
        row.status = APPROVED
        row.reviewed_by = teacher.id
        row.reviewed_at = datetime.now()
        if was_pending:
            question = submission.question
            assignment = question.assignment if question is not None else None
            title = assignment.title if assignment is not None else ""
            db.add(Notification(
                user_id=submission.student_id,
                type="review_approved",
                content=(
                    f"{teacher.name}已审核通过你《{title}》的批改结果，"
                    "去看看老师的诊断吧。"
                ),
                related_submission_id=submission.id,
            ))


def pending_reviews(db: Session) -> List[Submission]:
    """教师端待审核队列：pending 的提交按提交时间正序（先交先审）。"""
    return (
        db.query(Submission)
        .join(SubmissionReview, SubmissionReview.submission_id == Submission.id)
        .options(
            load_only(
                Submission.id,
                Submission.student_id,
                Submission.question_id,
                Submission.submitted_at,
            ),
            joinedload(Submission.student).load_only(
                User.id, User.name, User.student_no, User.role, User.created_at,
            ),
            joinedload(Submission.question)
            .load_only(
                Question.id,
                Question.assignment_id,
                Question.subject,
                Question.knowledge_point,
                Question.stem,
            )
            .joinedload(Question.assignment)
            .load_only(Assignment.id, Assignment.title),
        )
        .filter(SubmissionReview.status == PENDING)
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
