"""Verification submission concurrency regressions: python smoke_verification_concurrency.py."""
import faulthandler
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import User, Verification
from app.routers import student as student_router
from app.schemas import VerificationSubmitIn


class VerificationSubmissionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        faulthandler.dump_traceback_later(15, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        self.temporary = tempfile.TemporaryDirectory(prefix="remedi-verification-")
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(
            f"sqlite:///{Path(self.temporary.name) / 'verification.sqlite'}",
            connect_args={"check_same_thread": False, "timeout": 5},
            future=True,
        )
        self.addCleanup(self.engine.dispose)
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.commit()
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as db:
            user = User(name="并发验证学生", role="student")
            db.add(user)
            db.flush()
            self.user_id = user.id
            self.current_user = User(id=user.id, name=user.name, role=user.role)
            verification = Verification(
                student_id=user.id,
                knowledge_point="一次函数",
                variant_json=json.dumps({"prompt": "求 y=2x+1 在 x=1 时的值"}),
                status="pending",
                attempts=0,
            )
            db.add(verification)
            db.commit()
            self.verification_id = verification.id

    @staticmethod
    def _judge_result(passed):
        return {
            "passed": passed,
            "first_error_seq": None if passed else 1,
            "error_type": None if passed else "计算失误",
            "detail": "步骤判定完成",
            "steps": [],
        }

    def _submit(self):
        with Session(self.engine) as db:
            return student_router.submit_verification(
                self.verification_id,
                VerificationSubmitIn(steps=["3"]),
                db,
                self.current_user,
            )

    def test_parallel_failed_submissions_increment_each_attempt(self):
        barrier = threading.Barrier(2)

        def judge(*_args):
            barrier.wait(timeout=5)
            return self._judge_result(False)

        with patch.object(student_router.variant_gen, "judge_steps", side_effect=judge):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = [future.result(timeout=8) for future in [
                    pool.submit(self._submit), pool.submit(self._submit),
                ]]

        self.assertEqual(sorted(result["attempts"] for result in results), [1, 2])
        with Session(self.engine) as db:
            verification = db.get(Verification, self.verification_id)
            self.assertEqual(verification.attempts, 2)
            self.assertEqual(verification.status, "failed")

    def test_parallel_passed_submissions_cannot_overwrite_terminal_state(self):
        barrier = threading.Barrier(2)

        def judge(*_args):
            barrier.wait(timeout=5)
            return self._judge_result(True)

        with patch.object(student_router.variant_gen, "judge_steps", side_effect=judge):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self._submit) for _ in range(2)]
                results = []
                for future in futures:
                    try:
                        results.append(future.result(timeout=8))
                    except HTTPException as exc:
                        results.append(exc)

        self.assertEqual(sum(isinstance(result, HTTPException) for result in results), 1)
        rejected = next(result for result in results if isinstance(result, HTTPException))
        self.assertEqual(rejected.status_code, 400)
        with Session(self.engine) as db:
            verification = db.get(Verification, self.verification_id)
            self.assertEqual(verification.attempts, 1)
            self.assertEqual(verification.status, "passed")
            self.assertIsNotNone(verification.completed_at)


if __name__ == "__main__":
    unittest.main(verbosity=2)
