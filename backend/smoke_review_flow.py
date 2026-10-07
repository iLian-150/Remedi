#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v0.9.3 教师审核流全链冒烟（对独立临时库运行，不碰开发库）。

链路：种子数据 → 学生新提交（POST /student/submissions，走真实诊断管线）
→ 学生详情 pending_review 且无诊断 → 学生错题本/报告/简报里看不到这条
→ 教师 pending 队列有它 → 教师详情能看到完整诊断 → 教师 approve
→ 学生收到 review_approved 通知 → 学生详情可见诊断 → 错题本出现该错题
→ 种子历史数据在学生报告/错题本里照常可见（无审核行 = approved）。
"""
import os
import subprocess
import sys
import tempfile
import time

import httpx

BASE = "http://127.0.0.1:8077"
FAILURES = []


def check(name: str, cond: bool, extra: str = ""):
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name} {extra}")
    if not cond:
        FAILURES.append(name)


def login(client: httpx.Client, username: str, role: str) -> str:
    r = client.post(f"{BASE}/api/auth/login", json={"username": username, "role": role})
    r.raise_for_status()
    return r.json()["token"]


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="remedi_smoke_")
    db_path = os.path.join(tmp, "smoke.db")
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["LLM_PROVIDER"] = "mock"
    backend = os.path.dirname(os.path.abspath(__file__))

    seed = subprocess.run(
        [sys.executable, "seed.py", "--reset"], cwd=backend, env=env,
        capture_output=True, text=True,
    )
    if seed.returncode != 0:
        print(seed.stdout, seed.stderr)
        print("seed 失败")
        return 1

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8077"],
        cwd=backend, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        client = httpx.Client(timeout=30, trust_env=False)
        for _ in range(60):
            try:
                if client.get(f"{BASE}/api/health").status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        health = client.get(f"{BASE}/api/health").json()
        check("health 版本 0.9.3", health.get("version") == "0.9.3", str(health.get("version")))

        stu = login(client, "林小夏", "student")
        tea = login(client, "陈老师", "teacher")
        hs = {"Authorization": f"Bearer {stu}"}
        ht = {"Authorization": f"Bearer {tea}"}

        # 作业与题目
        detail = client.get(f"{BASE}/api/student/assignments/1", headers=hs).json()
        q1 = detail["questions"][0]
        check("种子作业题目可读", q1["stem"].startswith("解方程"), q1["stem"])

        # 种子历史数据在学生报告里可见（无审核行 = approved）
        report0 = client.get(f"{BASE}/api/student/report", headers=hs).json()
        math0 = next((s for s in report0 if s["subject"] == "math"), None)
        check("种子数据在学生报告可见", bool(math0 and math0["submission_count"] >= 1),
              f"count={math0 and math0['submission_count']}")
        mistakes0 = client.get(f"{BASE}/api/student/mistakes", headers=hs).json()
        seed_mistake_ids = {m["id"] for m in mistakes0 if m["id"] > 0}
        check("种子错题在错题本可见", len(seed_mistake_ids) >= 1, f"n={len(seed_mistake_ids)}")

        # 新提交：故意写错一步（移项未变号）→ 产生错题
        r = client.post(f"{BASE}/api/student/submissions", headers=hs,
                        json={"question_id": q1["id"], "steps": ["2x=7+3", "2x=10", "x=5"]})
        r.raise_for_status()
        created = r.json()
        sub_id = created["submission_id"]
        check("新提交响应为待审核占位",
              created["status"] == "pending_review" and created.get("review_status") == "pending",
              f"status={created['status']}")
        check("新提交响应不含诊断结论",
              created["steps"] == [] and created["errors"] == [] and created["first_error_seq"] is None)

        # 学生详情同样 pending 且无诊断
        d = client.get(f"{BASE}/api/student/submissions/{sub_id}", headers=hs).json()
        check("学生详情 pending 且无诊断",
              d["status"] == "pending_review" and d["errors"] == [] and d["steps"] == [])

        # 学生提交列表：该条 review_status=pending 且 error_count 不泄露
        lst = client.get(f"{BASE}/api/student/submissions", headers=hs).json()["items"]
        mine = next((s for s in lst if s["id"] == sub_id), None)
        check("提交列表标记待审核且错误数不泄露",
              bool(mine and mine["review_status"] == "pending" and mine["error_count"] == 0),
              str(mine and (mine["review_status"], mine["error_count"])))

        # 错题本/报告/简报看不到这条新错题
        mistakes1 = client.get(f"{BASE}/api/student/mistakes", headers=hs).json()
        new_ids = {m["id"] for m in mistakes1 if m["id"] > 0}
        check("待审核错题不进错题本", new_ids == seed_mistake_ids,
              f"before={len(seed_mistake_ids)} after={len(new_ids)}")
        briefing1 = client.get(f"{BASE}/api/student/briefing", headers=hs).json()
        check("简报待订正数不含待审核错题",
              briefing1["pending_corrections_count"] == len(seed_mistake_ids),
              f"briefing={briefing1['pending_corrections_count']} seed={len(seed_mistake_ids)}")

        # 订正待审核错题应被拦（先从教师详情拿到 error id）
        # 教师 pending 队列
        pend = client.get(f"{BASE}/api/teacher/reviews/pending", headers=ht).json()
        item = next((i for i in pend["items"] if i["submission_id"] == sub_id), None)
        check("教师待审核队列有这条", item is not None and pend["count"] >= 1,
              f"count={pend['count']}")
        check("队列项带学生/题目/错误数",
              bool(item and item["student"]["name"] == "林小夏" and item["error_count"] >= 1),
              str(item and item["error_count"]))

        # 教师详情：完整诊断可见
        rd = client.get(f"{BASE}/api/teacher/reviews/{sub_id}", headers=ht).json()
        check("教师审核详情含完整诊断",
              rd["review_status"] == "pending" and len(rd["diagnosis"]["steps"]) >= 2
              and len(rd["diagnosis"]["errors"]) >= 1,
              f"errors={len(rd['diagnosis']['errors'])}")
        err_id = rd["diagnosis"]["errors"][0]["id"]

        # 学生此时订正该错题 → 400 拦截
        rc = client.post(f"{BASE}/api/student/corrections", headers=hs,
                         json={"error_id": err_id, "content": "2x=7-3"})
        check("待审核时订正被拦截", rc.status_code == 400, f"code={rc.status_code}")

        # 学生此时拿该错题发起验证 → 400 拦截
        rv = client.post(f"{BASE}/api/student/verifications", headers=hs,
                         json={"knowledge_point": "一元一次方程", "source_error_id": err_id})
        check("待审核时验证被拦截", rv.status_code == 400, f"code={rv.status_code}")

        # 教师纠错（改后通过的前半段）：纠错不应给学生发提醒（诊断尚不可见）
        before_notes = client.get(f"{BASE}/api/student/notifications", headers=hs).json()
        corr_notes_before = [n for n in before_notes["items"] if n["type"] == "teacher_correction"]
        rc2 = client.post(f"{BASE}/api/teacher/errors/{err_id}/correct", headers=ht,
                          json={"error_type": "审题遗漏", "teacher_note": "审核时顺手改"})
        check("教师纠错接口可用", rc2.status_code == 200, f"code={rc2.status_code}")
        mid_notes = client.get(f"{BASE}/api/student/notifications", headers=hs).json()
        corr_notes_mid = [n for n in mid_notes["items"] if n["type"] == "teacher_correction"]
        check("待审核期间纠错不提前发学生提醒", len(corr_notes_mid) == len(corr_notes_before))

        # 教师通过
        ra = client.post(f"{BASE}/api/teacher/reviews/{sub_id}/approve", headers=ht)
        check("教师 approve 成功", ra.status_code == 200 and ra.json()["review_status"] == "approved")

        # 队列里消失
        pend2 = client.get(f"{BASE}/api/teacher/reviews/pending", headers=ht).json()
        check("通过后离开待审核队列",
              all(i["submission_id"] != sub_id for i in pend2["items"]))

        # 学生收到 review_approved 通知
        notes = client.get(f"{BASE}/api/student/notifications", headers=hs).json()
        approved_notes = [n for n in notes["items"]
                          if n["type"] == "review_approved" and n["related_submission_id"] == sub_id]
        check("学生收到审核通过通知", len(approved_notes) == 1,
              approved_notes[0]["content"] if approved_notes else "无")

        # 学生详情可见诊断，且错因是教师改后的
        d2 = client.get(f"{BASE}/api/student/submissions/{sub_id}", headers=hs).json()
        check("通过后学生详情可见诊断",
              d2["status"] == "graded" and len(d2["errors"]) >= 1
              and d2["errors"][0]["error_type"] == "审题遗漏",
              f"status={d2['status']} errors={len(d2['errors'])}")

        # 错题本出现该错题
        mistakes2 = client.get(f"{BASE}/api/student/mistakes", headers=hs).json()
        check("通过后错题进错题本", any(m["id"] == err_id for m in mistakes2))

        # approve 幂等：再通过一次不重复发通知
        client.post(f"{BASE}/api/teacher/reviews/{sub_id}/approve", headers=ht)
        notes2 = client.get(f"{BASE}/api/student/notifications", headers=hs).json()
        approved_notes2 = [n for n in notes2["items"] if n["type"] == "review_approved"]
        check("重复 approve 不重复发通知", len(approved_notes2) == len(approved_notes))

        # 批量通过：再交一份 → approve-all
        r2 = client.post(f"{BASE}/api/student/submissions", headers=hs,
                         json={"question_id": q1["id"], "steps": ["2x=7-3", "2x=4", "x=2"]})
        sub2 = r2.json()["submission_id"]
        rall = client.post(f"{BASE}/api/teacher/reviews/approve-all", headers=ht).json()
        check("批量通过计数正确", rall["approved_count"] == 1, str(rall))
        d3 = client.get(f"{BASE}/api/student/submissions/{sub2}", headers=hs).json()
        check("批量通过后学生可见（全对无错题）",
              d3["status"] == "graded" and d3["errors"] == [])

        # 会话列表带 message_count（任务 2 的后端前提）
        sess = client.get(f"{BASE}/api/student/agent/sessions", headers=hs).json()
        check("会话列表结构含 message_count",
              isinstance(sess, list) and (not sess or "message_count" in sess[0]))

        print()
        if FAILURES:
            print(f"失败 {len(FAILURES)} 项：{FAILURES}")
            return 1
        print("全部通过 ✔")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
