# 过程可疑识别冒烟（临时库 + mock provider）：
#   发布一元一次方程题 → 构造四种作答 →
#   (a) 全对完整链 → suspicious=False
#   (b) 中间步错、最终答案对 → True 且含 broken_chain；学生过审后追问换成过程追问
#   (c) 只写一步直接给对答案 → True 且含 leap
#   (d) 答案错 → False
#   (e) 一半步骤无法解析、答案对 → True 且含 unparseable_heavy（附加）
# 同时函数级直调 analyze_process 复核 (a)-(d)，并断言学生出参不含
# process_check / suspicious / 可疑 / 疑似 等字样。
# 运行前需先起服务（临时库 seed 后）：uvicorn app.main:app --port 8013，
# 且本脚本进程要用同一个 DATABASE_URL 才能函数级读到同一份数据。
import os
import sys

import requests

BASE = "http://127.0.0.1:8013"
fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name, extra if not cond else "")
    if not cond:
        fails.append(name)


def login(name, role):
    r = requests.post(f"{BASE}/api/auth/login", json={"username": name, "role": role})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


T = login("陈老师", "teacher")
S = login("林小夏", "student")

# ---------- 发布一道一元一次方程题（参考解 x=2） ----------
r = requests.post(f"{BASE}/api/teacher/assignments", headers=T, json={
    "title": "过程识别冒烟作业", "subject": "math",
    "questions": [
        {"type": "math", "prompt": "解方程：2x+3=7", "knowledge_point": "一元一次方程",
         "reference_answer": "x=2"},
    ],
})
check("发布作业 200", r.status_code == 200, r.text[:200])
qid = r.json()["questions"][0]["id"]


def submit(steps):
    r = requests.post(f"{BASE}/api/student/submissions", headers=S,
                      json={"question_id": qid, "steps": steps})
    r.raise_for_status()
    return r.json()["submission_id"]


def teacher_pc(sub_id):
    r = requests.get(f"{BASE}/api/teacher/reviews/{sub_id}", headers=T)
    r.raise_for_status()
    return r.json().get("process_check")


def codes(pc):
    return {s["code"] for s in (pc or {}).get("signals", [])}


# ---------- (a) 全对完整链 → False ----------
sub_a = submit(["2x+3=7", "2x=7-3", "2x=4", "x=2"])
pc_a = teacher_pc(sub_a)
check("(a) 教师详情带 process_check", pc_a is not None, str(pc_a))
check("(a) 全对完整链 suspicious=False", pc_a["suspicious"] is False, str(pc_a))

# ---------- (b) 中间步错、最终答案对 → broken_chain ----------
sub_b = submit(["2x=7+3", "x=2"])
pc_b = teacher_pc(sub_b)
check("(b) suspicious=True", pc_b["suspicious"] is True, str(pc_b))
check("(b) 含 broken_chain", "broken_chain" in codes(pc_b), str(pc_b))
check("(b) final/reference 均为 2",
      pc_b["final_answer"] == "2" and pc_b["reference_answer"] == "2", str(pc_b))

# ---------- (c) 只写一步直接给对答案 → leap ----------
sub_c = submit(["x=2"])
pc_c = teacher_pc(sub_c)
check("(c) suspicious=True", pc_c["suspicious"] is True, str(pc_c))
check("(c) 含 leap", "leap" in codes(pc_c), str(pc_c))

# ---------- (d) 答案错 → False ----------
sub_d = submit(["2x=7-3", "2x=4", "x=5"])
pc_d = teacher_pc(sub_d)
check("(d) 答案错 suspicious=False", pc_d["suspicious"] is False, str(pc_d))

# ---------- (e) 一半步骤无法解析、答案对 → unparseable_heavy ----------
sub_e = submit(["先把常数项移到右边", "x=2"])
pc_e = teacher_pc(sub_e)
check("(e) suspicious=True", pc_e["suspicious"] is True, str(pc_e))
check("(e) 含 unparseable_heavy", "unparseable_heavy" in codes(pc_e), str(pc_e))

# ---------- 函数级直调 analyze_process 复核 ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.database import SessionLocal  # noqa: E402
from app.models import Submission  # noqa: E402
from app.services.process_check import analyze_process  # noqa: E402

db = SessionLocal()
try:
    for label, sub_id, want in [("a", sub_a, False), ("b", sub_b, True),
                                ("c", sub_c, True), ("d", sub_d, False)]:
        sub = db.query(Submission).filter(Submission.id == sub_id).first()
        got = analyze_process(db, sub)
        check(f"函数级 ({label}) suspicious={want}", got["suspicious"] is want,
              str(got))
finally:
    db.close()

# ---------- 学生侧：(b) 过审后追问换成过程追问，且出参干净 ----------
r = requests.post(f"{BASE}/api/teacher/reviews/{sub_b}/approve", headers=T, json={})
check("教师通过 (b) 200", r.status_code == 200, r.text[:200])
r = requests.get(f"{BASE}/api/student/submissions/{sub_b}", headers=S)
r.raise_for_status()
body = r.json()
fu = body.get("follow_up_question") or ""
check("学生 (b) 追问是过程追问", "老师想听听" in fu and "第 1 步" in fu, fu)
raw = r.text
for banned in ["process_check", "suspicious", "可疑", "疑似", "顽固"]:
    check(f"学生出参不含「{banned}」", banned not in raw, raw[:200])

print()
if fails:
    print(f"失败 {len(fails)} 项：{fails}")
    sys.exit(1)
print("全部通过 ✔")
