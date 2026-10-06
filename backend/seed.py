#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remedi MVP 演示数据脚本。
用法：
    cd ~/workspace/remedi/backend
    python seed.py            # 建表并写入演示数据（已存在则跳过重复部分）
    python seed.py --reset    # 先清空所有表再写入

演示数据：
    - 1 名教师（陈老师）、2 名学生（林小夏 S2026001、陈默 S2026002）
    - 1 份作业「第一周数学+英语作业」：3 道数学题 + 1 篇作文题
    - 历史错误（走真实诊断管线生成，再回拨 created_at）：
        1. 林小夏 20 天前第 1 题移项未变号 → 概念混淆
           （用于演示：她再次在"一元一次方程"出错时 is_stubborn=true）
        2. 陈默 5 天前第 3 题分配律漏乘 → 概念混淆（教师已回标）
"""
import argparse
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app.database import SessionLocal, init_db, engine  # noqa: E402
from app.models import (  # noqa: E402
    Assignment, Base, Correction, Error, Essay, Question, Step, Submission, User,
)
from app.services.diagnosis import diagnose_submission  # noqa: E402


def backdate_error(db, error: Error, days_ago: int):
    """把某条 error 及其 submission 的时间回拨 days_ago 天（演示历史数据）。"""
    past = datetime.now() - timedelta(days=days_ago)
    error.created_at = past
    sub = db.query(Submission).filter(Submission.id == error.submission_id).first()
    if sub:
        sub.submitted_at = past
    db.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="清空所有表后重建")
    args = parser.parse_args()

    if args.reset:
        print("清空所有表…")
        Base.metadata.drop_all(bind=engine)
    init_db()
    db = SessionLocal()
    try:
        # ---- 用户 ----
        teacher = db.query(User).filter(User.name == "陈老师").first()
        if not teacher:
            teacher = User(name="陈老师", student_no=None, role="teacher")
            db.add(teacher)
        xiaxia = db.query(User).filter(User.name == "林小夏").first()
        if not xiaxia:
            xiaxia = User(name="林小夏", student_no="S2026001", role="student")
            db.add(xiaxia)
        chenmo = db.query(User).filter(User.name == "陈默").first()
        if not chenmo:
            chenmo = User(name="陈默", student_no="S2026002", role="student")
            db.add(chenmo)
        db.commit()
        print(f"用户：陈老师(id={teacher.id})、林小夏(id={xiaxia.id})、陈默(id={chenmo.id})")

        # ---- 作业与题目 ----
        assignment = db.query(Assignment).filter(Assignment.title == "第一周数学+英语作业").first()
        if not assignment:
            assignment = Assignment(
                title="第一周数学+英语作业",
                description="包含 3 道数学题与 1 篇英语作文",
                created_by=teacher.id,
            )
            db.add(assignment)
            db.commit()
            questions_data = [
                ("math", "一元一次方程", "解方程：2x+3=7", "x=2", 1),
                ("math", "完全平方公式", "解方程：(x+1)²=9", "x=2 或 x=-4", 2),
                ("math", "去括号", "解方程：2(x-3)=10", "x=8", 3),
                ("english", "英语写作",
                 "Write a short paragraph about your weekend (60-80 words).", None, 4),
            ]
            for subject, kp, stem, ans, order in questions_data:
                db.add(Question(assignment_id=assignment.id, subject=subject,
                                knowledge_point=kp, stem=stem,
                                standard_answer=ans, order_num=order))
            db.commit()
            print(f"作业 id={assignment.id}，4 道题目已创建")
        questions = {q.order_num: q for q in
                     db.query(Question).filter(Question.assignment_id == assignment.id).all()}

        # ---- 历史错误 1：林小夏 20 天前，第 1 题移项未变号 ----
        exists = (
            db.query(Error)
            .join(Submission, Error.submission_id == Submission.id)
            .filter(Submission.student_id == xiaxia.id,
                    Error.knowledge_point == "一元一次方程")
            .first()
        )
        if not exists:
            _, _, errors = diagnose_submission(
                db, xiaxia, questions[1],
                ["2x+3=7", "2x=7+3", "2x=10", "x=5"],
            )
            for e in errors:
                backdate_error(db, e, 20)
            print(f"历史错误1：林小夏 20 天前「一元一次方程」{errors[0].error_type}（已回拨时间）")
        else:
            print("历史错误1：已存在，跳过")

        # ---- 历史错误 2：陈默 5 天前，第 3 题分配律漏乘（教师已回标） ----
        exists2 = (
            db.query(Error)
            .join(Submission, Error.submission_id == Submission.id)
            .filter(Submission.student_id == chenmo.id,
                    Error.knowledge_point == "去括号")
            .first()
        )
        if not exists2:
            _, _, errors = diagnose_submission(
                db, chenmo, questions[3],
                ["2(x-3)=10", "2x-3=10", "2x=13", "x=6.5"],
            )
            for e in errors:
                backdate_error(db, e, 5)
            # 教师回标演示
            e0 = errors[0]
            e0.teacher_corrected = True
            e0.teacher_note = "已和学生当面讲解分配律，确认是概念问题"
            db.commit()
            print(f"历史错误2：陈默 5 天前「去括号」{e0.error_type}（教师已回标）")
        else:
            print("历史错误2：已存在，跳过")

        print("\nSeed 完成。登录演示：POST /api/auth/login {\"username\": \"林小夏\", \"role\": \"student\"}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
