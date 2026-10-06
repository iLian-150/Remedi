# Remedi MVP · 后端

多学科智能作业批改与学习诊断系统（MVP）：跑通「提交作业 → 分步诊断 → 学习记忆 → 班级反馈」完整闭环。

技术栈：Python 3.12 + FastAPI + SQLAlchemy + SQLite（表结构按 PostgreSQL 兼容设计）+ sympy + pydantic。

## 快速开始

```bash
cd ~/workspace/remedi/backend

# 1. 安装依赖（本机系统 pip 受 PEP 668 保护，用 venv 隔离安装）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 写入演示数据（1 名教师、2 名学生、1 份作业、2 条历史错误）
.venv/bin/python seed.py
# 重新来一遍：.venv/bin/python seed.py --reset

# 3. 启动服务
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

- 接口文档（Swagger）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health
- 接口契约：`../docs/api-contract.md`（冻结版，前后端联调依据）
- 表设计：`../docs/schema-design.md`

## 演示流程（curl）

```bash
# 登录（学生林小夏；用户不存在会自动创建）
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"林小夏","role":"student"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 提交数学作业：第 1 题，故意在 step2 移项不变号
# 注意 steps 只传作答步骤，不要传题干（题干自动作为 seq=0）
curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"林小夏","role":"student"}' > /dev/null
curl -s -X POST localhost:8000/api/student/submissions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question_id":1,"steps":["2x+3=7","2x=7+3","2x=10","x=5"]}' | python3 -m json.tool
# 预期：step1 报错 error_type=概念混淆，is_stubborn=true
# （因为 seed 预置了她 20 天前在同一知识点的历史错误）

# 提交英语作文
curl -s -X POST localhost:8000/api/student/essays \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question_id":4,"text":"Last weekend was fun. I go to the park with my friend. He like playing football very much. We plays games and eat snacks."}' \
  | python3 -m json.tool

# 教师登录并查看高频错题 TopN
TTOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"陈老师","role":"teacher"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
curl -s "localhost:8000/api/teacher/stats/top-questions?n=10" \
  -H "Authorization: Bearer $TTOKEN" | python3 -m json.tool

# 教师一键纠错（把 error 9 的分类改为"计算失误"并备注）
curl -s -X POST localhost:8000/api/teacher/errors/9/correct \
  -H "Authorization: Bearer $TTOKEN" -H 'Content-Type: application/json' \
  -d '{"error_type":"计算失误","teacher_note":"经核实是抄错数字"}' | python3 -m json.tool
```

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./remedi.db` | 数据库连接串；切 PG 改为 `postgresql+psycopg2://…` |
| `LLM_PROVIDER` | `mock` | `mock`（确定性，无需 key）\| `deepseek` |
| `DEEPSEEK_API_KEY` | 空 | 未配置时 DeepSeek 自动降级为 Mock |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | — |
| `DEEPSEEK_MODEL` | `deepseek-chat` | — |
| `STUBBORN_WINDOW_DAYS` | `30` | 顽固误区判定窗口（天） |
| `CORS_ORIGINS` | `*` | 允许的前端来源，逗号分隔 |

**注意**：不要在代码或文档里硬编码任何真实 API key，一律走环境变量。

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI 入口、CORS、路由挂载
│   ├── config.py          # 环境变量配置
│   ├── database.py        # engine / Session / 建表
│   ├── models.py          # SQLAlchemy 模型（8 张表）
│   ├── schemas.py         # pydantic 请求/响应模型
│   ├── auth.py            # mock 登录、Bearer 校验、角色守卫
│   ├── services/
│   │   ├── mathparse.py   # sympy 安全解析（parse_expr 白名单）
│   │   ├── diagnosis.py   # 分步诊断、等价性判定、误区模式库、顽固判定、订正判定
│   │   ├── providers.py   # LLMProvider 抽象 + Mock + DeepSeek（含降级）
│   │   ├── essays.py      # 作文评分落库
│   │   └── stats.py       # TopN / 知识点排行 / 学生画像
│   └── routers/
│       ├── auth.py        # /api/auth/*
│       ├── student.py     # /api/student/*
│       ├── teacher.py     # /api/teacher/*
│       └── health.py      # /api/health
├── seed.py                # 演示数据
├── requirements.txt
└── README.md
```

## 核心逻辑说明

**数学分步诊断**（`services/diagnosis.py`）：
- step0 = 题干（仅参考）；从题干中提取等式作为初始基准，提不出则以第一个可解析的学生步骤为基准。
- 逐个验证等价性：表达式用 `simplify(e1-e2)==0`；等式移项得 f1、f2，`simplify(f1-f2)==0` 或 `f2/f1` 为非零常数即等价。
- 找到**第一个**不等价步骤即停止（后续记 skipped），做错因分类。
- 解析失败的步骤记 `无法解析`（置信度 0.3），流程继续、基准不变。

**错因分类**（先规则后模型）：误区模式库（(a±b)² 漏交叉项 / 移项不变号 / 分配律漏乘）命中→概念混淆（0.85）；数字微调 ±1/±2/±3 后等价→计算失误（0.7）；兜底→审题遗漏（0.5）。之后调 `LLMProvider.classify_error` 复核（Mock 原样返回）。

**顽固误区**：同学生同知识点过去 N 天（默认 30）内已有错误 → `is_stubborn=true`。

**认证**：纯 mock，无密码。`POST /api/auth/login` 传用户名+角色即得 token（`mock-<id>`），后续请求带 `Authorization: Bearer <token>`。生产必须替换。

## 已知局限（诊断逻辑）

1. **等价性是数学等价，不是教学等价**：如 `x²=4x → x=4`（两边同除以 x，丢了 x=0 的解）在数学上不等价，会被判错——教学上可能算"步骤跳跃"，目前无法区分。
2. **模式库只覆盖三类常见误区**（平方展开漏交叉项、移项不变号、分配律漏乘），且移项检测主要针对线性方程；其他误区走兜底「审题遗漏」（置信度 0.5），依赖教师复核/回标。
3. **算术偏差检测只试 ±1/±2/±3 的数字微调**，复杂口算错误（如 7×8=54）识别不到。
4. **隐式乘法与符号**：`2x` 可解析；但 `xy` 会被当作单个变量名；中文注释会被剥离，残留中文则整步记无法解析。
5. **订正判定**只验证"订正内容与出错前一步等价"，不检查订正是否真正修复了错误类型。
6. **Mock 作文评分是启发式**（词数/连接词/简单正则语法检查），不是真正的语言模型评分；切 `LLM_PROVIDER=deepseek` 可获得真实评分。
7. **SQLite 并发写入能力弱**，仅适合 MVP 演示；生产切 PostgreSQL（表结构已兼容，改 `DATABASE_URL` 即可）。
