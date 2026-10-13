# 教师复核流：低置信度 AI 错因同步进入教师队列，学生可立即查看并订正。
# 分数和审核通过提醒仍等教师处理后放行。
#
# 学生的学习报告/画像可以选择排除 pending 记录；错题本与订正待办不排除。
from datetime import datetime
import math
from typing import Iterable, List, Optional, Set, Tuple

from sqlalchemy import case, func, tuple_
from sqlalchemy.orm import Session, joinedload

from ..models import Error, Notification, Question, Step, Submission, SubmissionReview
from .confidence import normalize_confidence

PENDING = "pending"
APPROVED = "approved"
REVIEW_THRESHOLD = 0.60


def create_pending_review(db: Session, submission: Submission) -> SubmissionReview:
    """实时批改入口产生新提交后调用：建一条 pending 审核行（幂等，已有行不覆盖）。"""
    return create_pending_reviews(db, [submission])[submission.id]


def create_pending_reviews(
    db: Session,
    submissions: Iterable[Submission],
    *,
    existing_rows: Optional[Iterable[SubmissionReview]] = None,
) -> dict[int, SubmissionReview]:
    """幂等地为多条提交建待审行；已有记录按批读取，最后一次提交。"""
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
    if added:
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


def review_reasons(
    db: Session,
    submission: Submission,
    confidence_signals: Iterable[float] = (),
    *,
    assignment_context: Optional[Tuple[List[Submission], int, int]] = None,
    step_statuses: Optional[Iterable[str]] = None,
    error_confidences: Optional[Iterable[float]] = None,
) -> List[str]:
    """返回触发教师复核的原因，统一步骤率、错因和视觉置信度口径。"""
    reasons = []
    if step_statuses is None:
        step_statuses = [row[0] for row in db.query(Step.status).filter(
            Step.submission_id == submission.id,
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).all()]
    else:
        step_statuses = list(step_statuses)
    if step_statuses:
        correct = sum(1 for value in step_statuses if value == "ok")
        accuracy = correct / len(step_statuses)
        if accuracy < REVIEW_THRESHOLD:
            reasons.append("作答步骤正确率低于 60%")

    if assignment_context is None:
        assignment_context = assignment_accuracy_context(db, submission)
    if assignment_context:
        _, assignment_correct, assignment_total = assignment_context
        if assignment_total > 0 and assignment_correct / assignment_total < REVIEW_THRESHOLD:
            reasons.append("本次作业正确率低于 60%")

    confidences = error_confidences
    if confidences is None:
        confidences = [
            float(row[0])
            for row in db.query(Error.confidence)
            .filter(Error.submission_id == submission.id)
            .all()
        ]
    if any(not math.isfinite(value) or value < REVIEW_THRESHOLD for value in confidences):
        reasons.append("错因判断置信度低于 60%")

    normalized_signals = []
    for raw in confidence_signals:
        normalized_signals.append(normalize_confidence(raw))
    if any(value < REVIEW_THRESHOLD for value in normalized_signals):
        reasons.append("图片或步骤判断置信度低于 60%")
    return reasons


def needs_teacher_review(db: Session, submission: Submission,
                         confidence_signals: Iterable[float] = (), *,
                         assignment_context: Optional[Tuple[List[Submission], int, int]] = None) -> bool:
    """单题正确率、本次作业已批改部分正确率、错因或视觉置信度低于 60% 时送审。

    正确率按 seq >= 1 且已判定的作答步骤计算；作业累计率跨学科统计已批改提交。
    视觉路径同时检查整图和每步判断置信度。
    """
    return bool(review_reasons(
        db, submission, confidence_signals, assignment_context=assignment_context
    ))


def create_review_if_needed(db: Session, submission: Submission,
                            confidence_signals: Iterable[float] = ()) -> Optional[SubmissionReview]:
    """按作答与视觉置信度决定是否建立待审核记录。"""
    assignment_context = assignment_accuracy_context(db, submission)
    if not needs_teacher_review(
        db, submission, confidence_signals, assignment_context=assignment_context
    ):
        return None
    submissions_to_review = [submission]
    if assignment_context:
        latest_submissions, correct, total = assignment_context
        if total > 0 and correct / total < REVIEW_THRESHOLD:
            # 作业整体低于阈值时，把该学生整份作业已批改题目的最新提交一起送审，
            # 教师窗口能看到完整作业，卡片正确率也按整份作业计算。
            submissions_to_review = list(latest_submissions)
            if all(item.id != submission.id for item in submissions_to_review):
                submissions_to_review.append(submission)
    rows_by_id = create_pending_reviews(db, submissions_to_review)
    return rows_by_id[submission.id]


def backfill_missing_review_records(db: Session) -> int:
    """把尚无审核行、且仍是该生该作业最新作答的待审核提交补入队列。

    正常提交会实时创建审核行；此补偿处理覆盖审核规则上线前已提交、后来才纳入
    当前作业的数据。按可从数据库恢复的作答率、作业累计率和错因置信度判断；
    已有 approved 行不回退，旧作答若已被新作答替代也不补审。
    """
    latest_graded = (
        db.query(
            Submission.id.label("submission_id"),
            func.row_number().over(
                partition_by=(Submission.student_id, Submission.question_id),
                order_by=(Submission.submitted_at.desc(), Submission.id.desc()),
            ).label("rank"),
        )
        .filter(Submission.status == "graded")
        .subquery()
    )
    candidates = (
        db.query(Submission)
        .join(latest_graded, latest_graded.c.submission_id == Submission.id)
        .outerjoin(SubmissionReview, SubmissionReview.submission_id == Submission.id)
        .options(joinedload(Submission.question))
        .filter(
            latest_graded.c.rank == 1,
            SubmissionReview.submission_id.is_(None),
        )
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
    contexts = assignment_accuracy_contexts(db, candidates)
    latest_ids_by_key = {
        key: {submission.id for submission in context[0]}
        for key, context in contexts.items()
        if context
    }
    candidate_ids = [submission.id for submission in candidates]
    step_statuses_by_submission = {}
    error_confidences_by_submission = {}
    # Bound IN lists for SQLite while keeping the startup backfill query count
    # proportional to batches instead of the number of historical submissions.
    for start in range(0, len(candidate_ids), 500):
        id_chunk = candidate_ids[start:start + 500]
        for submission_id, status in db.query(
            Step.submission_id, Step.status
        ).filter(
            Step.submission_id.in_(id_chunk),
            Step.seq >= 1,
            Step.status.in_(("ok", "error", "unparseable")),
        ).all():
            step_statuses_by_submission.setdefault(submission_id, []).append(status)
        for submission_id, confidence in db.query(
            Error.submission_id, Error.confidence
        ).filter(Error.submission_id.in_(id_chunk)).all():
            error_confidences_by_submission.setdefault(submission_id, []).append(
                float(confidence)
            )

    submissions_to_review = {}
    for submission in candidates:
        question = submission.question
        if question is None:
            continue
        key = (submission.student_id, question.assignment_id)
        context = contexts.get(key)
        if not context:
            continue

        latest_submissions, correct, total = context
        if submission.id not in latest_ids_by_key.get(key, set()):
            continue
        if not review_reasons(
            db,
            submission,
            assignment_context=context,
            step_statuses=step_statuses_by_submission.get(submission.id, []),
            error_confidences=error_confidences_by_submission.get(submission.id, []),
        ):
            continue

        targets = (
            latest_submissions
            if total > 0 and correct / total < REVIEW_THRESHOLD
            else [submission]
        )
        submissions_to_review.update({item.id: item for item in targets})

    if not submissions_to_review:
        return 0
    submission_ids = list(submissions_to_review)
    existing_rows = {}
    for start in range(0, len(submission_ids), 500):
        for row in db.query(SubmissionReview).filter(
            SubmissionReview.submission_id.in_(submission_ids[start:start + 500])
        ).all():
            existing_rows[row.submission_id] = row
    existing_ids = set(existing_rows)
    rows = create_pending_reviews(
        db,
        submissions_to_review.values(),
        existing_rows=existing_rows.values(),
    )
    return sum(
        1 for submission_id, row in rows.items()
        if submission_id not in existing_ids and row.status == PENDING
    )


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
                       *, notify: bool = True) -> SubmissionReview:
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
    db.commit()
    db.refresh(row)
    return row


def pending_reviews(db: Session) -> List[Submission]:
    """教师端待审核队列：pending 的提交按提交时间正序（先交先审）。"""
    return (
        db.query(Submission)
        .join(SubmissionReview, SubmissionReview.submission_id == Submission.id)
        .options(
            joinedload(Submission.student),
            joinedload(Submission.question).joinedload(Question.assignment),
        )
        .filter(SubmissionReview.status == PENDING)
        .order_by(Submission.submitted_at.asc(), Submission.id.asc())
        .all()
    )
