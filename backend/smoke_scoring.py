# 评分系统端到端冒烟（临时库 + mock provider）：发布带分值作业 → 学生交错步
# → AI 分按公式 → pending 看不到分 → 教师改分通过 → 学生见 final 分
# → report/scores 聚合 → 无配置老作业默认均分 → 超满分改分被拦。
import sys

import requests

BASE = "http://127.0.0.1:8012"
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

# ---------- 1. 发布带分值作业：总分 100，两题各 50% ----------
r = requests.post(f"{BASE}/api/teacher/assignments", headers=T, json={
    "title": "评分冒烟作业", "subject": "math", "total_score": 100,
    "questions": [
        {"type": "math", "prompt": "解方程：2x+3=7", "knowledge_point": "一元一次方程",
         "reference_answer": "x=2", "weight_pct": 50},
        {"type": "math", "prompt": "解方程：2(x-3)=10", "knowledge_point": "去括号",
         "reference_answer": "x=8", "weight_pct": 50},
    ],
})
check("发布带分值作业 200", r.status_code == 200, r.text[:200])
a = r.json()
check("出参 total_score=100", a["total_score"] == 100, str(a.get("total_score")))
check("出参 weight_pct=50/50", [q["weight_pct"] for q in a["questions"]] == [50, 50],
      str([q.get("weight_pct") for q in a["questions"]]))
q1, q2 = a["questions"][0]["id"], a["questions"][1]["id"]

# ---------- 2. 学生交 Q1 错步：1 ok / 4 步 → AI 分 = 50 * 0.25 = 12.5 ----------
r = requests.post(f"{BASE}/api/student/submissions", headers=S, json={
    "question_id": q1, "steps": ["2x+3=7", "2x=7+3", "2x=10", "x=5"],
})
check("学生提交 200", r.status_code == 200, r.text[:200])
sub1 = r.json()["submission_id"]
check("提交响应 pending_review", r.json()["status"] == "pending_review", r.json()["status"])
check("提交响应无分", r.json().get("score") is None, str(r.json().get("score")))

# 学生详情（pending）：看不到分
r = requests.get(f"{BASE}/api/student/submissions/{sub1}", headers=S)
check("pending 详情无分", r.json().get("score") is None and r.json()["status"] == "pending_review",
      r.text[:200])

# ---------- 3. 教师审核详情：满分 50、AI 分 12.5、步骤 1/4 ----------
r = requests.get(f"{BASE}/api/teacher/reviews/{sub1}", headers=T)
d = r.json()
check("审核详情带 score", d.get("score") is not None, r.text[:200])
sc = d["score"]
check("本题满分 50", sc["question_max"] == 50, str(sc))
check("AI 分 12.5（公式）", sc["ai_score"] == 12.5, str(sc))
check("步骤对了 1/4", (sc["ok_steps"], sc["total_steps"]) == (1, 4), str(sc))

# ---------- 4. 超满分改分被拦 ----------
r = requests.post(f"{BASE}/api/teacher/reviews/{sub1}/approve", headers=T,
                  json={"final_score": 60})
check("改分超满分 400", r.status_code == 400, str(r.status_code))

# ---------- 5. 教师改分 20 并通过 → 学生见 final=20 ----------
r = requests.post(f"{BASE}/api/teacher/reviews/{sub1}/approve", headers=T,
                  json={"final_score": 20})
check("改分通过 200", r.status_code == 200, r.text[:200])
r = requests.get(f"{BASE}/api/student/submissions/{sub1}", headers=S)
sd = r.json()
check("学生详情已放行", sd["status"] != "pending_review", sd["status"])
check("学生见 final 分 20/50", sd["score"]["score"] == 20 and sd["score"]["max_score"] == 50,
      str(sd.get("score")))
check("成绩单累计 20/100", sd["score"]["assignment_score"] == 20 and sd["score"]["assignment_total"] == 100,
      str(sd.get("score")))

# 提交记录列表带分
r = requests.get(f"{BASE}/api/student/submissions", headers=S)
item = next(i for i in r.json()["items"] if i["id"] == sub1)
check("提交列表带分 20/50", item["score"] == 20 and item["max_score"] == 50, str(item))

# ---------- 6. Q2 全对提交 → 不改分通过 → ai=50 落定；报告聚合 ----------
r = requests.post(f"{BASE}/api/student/submissions", headers=S, json={
    "question_id": q2, "steps": ["2(x-3)=10", "2x-6=10", "2x=16", "x=8"],
})
sub2 = r.json()["submission_id"]
r = requests.get(f"{BASE}/api/teacher/reviews/{sub2}", headers=T)
check("Q2 全对 AI 分 50", r.json()["score"]["ai_score"] == 50, str(r.json().get("score")))
r = requests.post(f"{BASE}/api/teacher/reviews/{sub2}/approve", headers=T, json={})
check("不带 body 改分的通过兼容", r.status_code == 200, str(r.status_code))
r = requests.get(f"{BASE}/api/student/submissions/{sub2}", headers=S)
check("Q2 final=ai=50", r.json()["score"]["score"] == 50, str(r.json().get("score")))

r = requests.get(f"{BASE}/api/student/report/scores", headers=S)
rep = r.json()
mine = next((i for i in rep["items"] if i["assignment_title"] == "评分冒烟作业"), None)
check("报告含冒烟作业", mine is not None, str(rep)[:300])
if mine:
    check("报告聚合 70/100 rate .7",
          mine["score"] == 70 and mine["max_score"] == 100 and abs(mine["rate"] - 0.7) < 1e-6,
          str(mine))
check("报告 subjects 含 math", any(s["subject"] == "math" for s in rep["subjects"]), str(rep["subjects"]))
check("报告 overall 有值", rep["overall_avg_rate"] is not None, str(rep["overall_avg_rate"]))

# ---------- 7. 无配置老作业：默认总分 100 + 均分，不报错 ----------
r = requests.post(f"{BASE}/api/teacher/assignments", headers=T, json={
    "title": "无配置老作业", "subject": "math",
    "questions": [
        {"type": "math", "prompt": "解方程：2x+3=7", "knowledge_point": "一元一次方程", "reference_answer": "x=2"},
        {"type": "math", "prompt": "解方程：2(x-3)=10", "knowledge_point": "去括号", "reference_answer": "x=8"},
        {"type": "math", "prompt": "解方程：(x+1)²=9", "knowledge_point": "完全平方公式", "reference_answer": "x=2 或 x=-4"},
    ],
})
check("无配置发布 200", r.status_code == 200, r.text[:200])
legacy = r.json()
check("默认总分 100", legacy["total_score"] == 100, str(legacy.get("total_score")))
lq = legacy["questions"][0]["id"]
r = requests.post(f"{BASE}/api/student/submissions", headers=S, json={
    "question_id": lq, "steps": ["2x+3=7", "2x=7-3", "2x=4", "x=2"],
})
lsub = r.json()["submission_id"]
r = requests.get(f"{BASE}/api/teacher/reviews/{lsub}", headers=T)
lsc = r.json()["score"]
check("均分满分 33.3（100/3）", abs(lsc["question_max"] - 33.3) < 0.05, str(lsc))
check("全对 AI 分=满分", abs(lsc["ai_score"] - lsc["question_max"]) < 0.05, str(lsc))
r = requests.post(f"{BASE}/api/teacher/reviews/{lsub}/approve", headers=T)  # 无 body
check("无 body 通过 200", r.status_code == 200, str(r.status_code))
r = requests.get(f"{BASE}/api/student/submissions/{lsub}", headers=S)
check("老作业学生见分", r.json()["score"] is not None and r.json()["score"]["score"] > 0,
      str(r.json().get("score")))

print("\n失败项：" + str(fails) if fails else "\n全部通过 ✔")
sys.exit(1 if fails else 0)
