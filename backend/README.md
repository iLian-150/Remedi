# Remedi 后端

多学科智能作业批改与学习诊断系统后端，提供教师端、学生端、作业批改、订正、学习记忆、聊天和学科知识库等 API。

技术栈：Python 3.11+ + FastAPI + SQLAlchemy + SQLite（表结构按 PostgreSQL 兼容设计）+ sympy + pydantic。

知识库 PDF 导入使用 PyMuPDF 1.x（`pymupdf>=1.24.3,<2`）。扫描版文档的文字识别还需要在后端运行主机安装 Tesseract OCR 和 `chi_sim`、`eng` 语言数据；没有 OCR 时，含可提取文字层的 PDF 仍可导入，扫描页会失败并保留可重试任务。

## 快速开始

```powershell
# 在仓库根目录创建共享虚拟环境并安装依赖
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt

# 从仓库根目录启动 API（开发端口 8000）
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000

# 可选：仅本地演示需要时写入演示数据
.\.venv\Scripts\python.exe backend/seed.py
```

Linux/macOS 可将 `.venv\Scripts\python.exe` 替换为 `.venv/bin/python`。

- 接口文档（Swagger）：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health
- 接口契约：`../docs/api-contract.md`（当前前后端联调依据）
- 表设计：`../docs/schema-design.md`

当前服务器前端由宝塔 Nginx 在 `5001` 提供 `/remedi/frontend/dist`，后端由宝塔 Python 项目在 `127.0.0.1:5000` 运行，Milvus 等依赖使用 Docker。后端依赖安装在该项目选定的 Python 虚拟环境中。

宝塔后端项目的环境变量选择「从文件加载」，文件为 `/remedi/deploy/load_backend_model_env.sh`。该脚本从 `/remedi/.env` 读取 `LLM_*`、`DASHSCOPE_*`、`RAG_*`，不覆盖数据库和上传目录设置；修改配置后重启 Python 项目。`/remedi/.env` 权限保持 `600`，所有者为运行账户 `www`，密钥只保存在该文件中；不要复制密钥到面板字段、脚本或 Git。宝塔生成的项目环境文件只引用加载脚本。

原生后端会把默认 Docker 地址 `http://milvus:19530` 转为本机映射地址 `http://127.0.0.1:19530`，不修改 `.env`，自定义 Milvus 地址保持原样。配置文件缺失或模型凭证不完整时，网站和健康检查仍可启动；需要模型的操作返回错误，向量检索按既有规则回退关键词检索。

原生后端与旧 Docker 后端使用不同数据库时，在 `.env` 设置独立的 `RAG_NATIVE_MILVUS_COLLECTION` 前缀（例如 `remedi_subject_knowledge_qwen37_flash_native`）。加载脚本仅为原生进程覆盖集合前缀，保留 Docker 的 `RAG_MILVUS_COLLECTION`；每科仍使用 `前缀_学科`。新前缀应从当前数据库资料建立索引，不复用另一数据库的片段 ID，也不删除旧集合。

生产环境由宝塔 Python 项目原生运行后端，工作目录为 `/remedi/backend`，监听 `127.0.0.1:5000`。Docker Compose 仅运行 Milvus、etcd 和 MinIO；向量服务说明见 [Milvus 与 RAG 部署说明](../docs/milvus-rag.md)。本地和生产环境默认不写入演示数据；仅在需要本地演示时手动运行 `seed.py`。

Ubuntu/Debian 原生部署可在仓库目录运行 `python3 deploy/install_native_ocr.py`。脚本使用服务器现有的可信 APT 索引下载 ARM64/AMD64 软件包，仅解包到 `/remedi/runtime`，不安装系统软件包，也不执行包内安装脚本。校验中英文语言包后原子切换 `runtime/ocr`，保留旧版本；包版本和 SHA256 记录在对应版本的 `manifest.json`。APT 索引无可用候选或软件包下载失败时会停止，不修改系统源或全局配置。

安装后在服务器 `.env` 设置 `RAG_OCR_EXECUTABLE=/remedi/runtime/ocr/bin/tesseract` 并重启后端。共享库路径和语言数据目录只对 OCR 子进程生效；Docker 镜像继续使用默认命令 `tesseract`。该运行目录须在目标主机生成，不应复制到其他系统或提交 Git。

## 演示流程（curl）

```bash
# 登录（学生林小夏；须已由教师录入班级名册）
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"林小夏","role":"student","student_no":"S2026001"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 提交数学作业：第 1 题，故意在 step2 移项不变号
# 注意 steps 只传作答步骤，不要传题干（题干自动作为 seq=0）
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
  -d '{"role":"teacher","subject":"math"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
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
| `LLM_PROVIDER` | `bailian` | 阿里云百炼；模型未配置或调用失败时明确报错，不自动切 Mock |
| `DASHSCOPE_API_KEY` | 空 | 示例不含真实百炼 API Key；实际凭证只保存在服务器环境配置 |
| `DASHSCOPE_BASE_URL` | 按工作空间配置 | 使用控制台工作空间专属 APIHost，并附加 `/compatible-mode/v1`，地域须与账号一致 |
| `DASHSCOPE_MODEL` | `kimi-k3` | Kimi-K3 文本问答模型，始终启用思考 |
| `DASHSCOPE_VISION_MODEL` | `kimi-k3` | 图片识别与讲解模型；生产环境在服务器 `.env` 中设为 `qwen3-vl-plus` |
| `RAG_MILVUS_COLLECTION` | `remedi_subject_knowledge_qwen37_flash` | 新向量模型使用独立集合，保留原集合 |
| `RAG_EMBEDDING_MODEL` | `qwen3.7-text-embedding-flash` | 学科知识库向量化模型，通过百炼接口调用 |
| `RAG_EMBEDDING_DIMENSIONS` | `1024` | 向量维度；变更模型或维度后按部署说明使用匹配的 Milvus 集合并重建索引 |
| `RAG_RERANK_MODEL` | `qwen3.7-text-rerank` | 候选片段的模型重排；不可用时回退本地重排 |
| `RAG_RERANK_TIMEOUT_SECONDS` | `10` | 模型重排请求等待上限（秒） |
| `SEED_DEMO_DATA` | `false` | 默认关闭应用启动时的演示数据初始化；本地演示数据可通过 `seed.py` 手动生成 |
| `LLM_TIMEOUT_SECONDS` | `120` | 对话模型等待上限（秒） |
| `STUBBORN_WINDOW_DAYS` | `30` | 顽固误区判定窗口（天） |
| `CORS_ORIGINS` | `*` | 允许的前端来源，逗号分隔 |

**注意**：不要在代码或文档里硬编码任何真实 API key，一律走环境变量。

工作空间专属地址示例为 `https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`；从百炼控制台复制实际 APIHost，并按账号替换工作空间标识和地域。模型可用性通过实际请求验证。模型配置不完整或暂不可用时，网站、数据库与健康检查仍可启动；向量检索回退 BM25，模型重排调用失败时回退本地重排并返回安全警告。未配置凭证或将 `RAG_RERANK_MODEL` 设为空时，仅使用本地重排。知识库试查响应新增 `rerank_mode`（`model | local`），可分别确认重排方式与 `retrieval_mode`（`bm25 | hybrid`）表示的召回方式。

`Kimi-K3` 的 `enable_thinking` 与 `preserve_thinking` 始终开启。工具调用循环仅在本次请求的内存中保留并回传 `reasoning_content`，确保后续工具轮符合模型协议；界面、SSE 回复正文及持久化聊天记录只保留可见答案。接通有效模型配置后，从教师端学科知识库重建索引，将旧资料同步到新集合 `remedi_subject_knowledge_qwen37_flash`。

## 目录结构

```
backend/
├── app/
│   ├── main.py            # FastAPI 入口、CORS、路由挂载
│   ├── lifespan.py        # 数据库初始化与进程级后台任务
│   ├── config.py          # 环境变量配置
│   ├── database.py        # engine / Session / 建表
│   ├── models.py          # SQLAlchemy 数据模型
│   ├── schemas.py         # 兼容导入入口
│   ├── api_schemas/       # 按通用、学生、教师、会话和验证域拆分的 Pydantic 模型
│   ├── auth.py            # mock 登录、Bearer 校验、角色守卫
│   ├── services/
│   │   ├── mathparse.py   # 白名单 AST 数学解析，不执行输入代码
│   │   ├── diagnosis.py   # 分步诊断、等价性判定、误区模式库、顽固判定、订正判定
│   │   ├── providers.py   # 阿里云百炼 Provider；失败明确报错
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

## 后端模块约定

新增代码按以下边界放置；整理存量代码时保持 API 路径、请求/响应字段和错误语义不变：

- `main.py` 负责应用装配；数据库初始化和进程级后台任务由 `lifespan.py` 管理。
- `routers/` 负责 HTTP 参数、认证依赖、状态码和响应。业务规则优先放到 `services/`，避免路由间互相导入。
- `api_schemas/` 按通用、学生、教师、会话和验证域维护 Pydantic 模型。`schemas.py` 仅保留旧导入路径的兼容转发。
- `services/` 承载业务流程和外部服务调用；`models.py` 与 `database.py` 分别维护持久化模型和会话/建表。
- 后台任务由 lifespan 启停，任务异常记录安全摘要；请求依赖的数据库会话由 `get_db` 管理，独立任务自行创建并关闭会话。

## 核心逻辑说明

**数学分步诊断**（`services/diagnosis.py`）：
- step0 = 题干（仅参考）；从题干中提取等式作为初始基准，提不出则以第一个可解析的学生步骤为基准。
- 逐个验证等价性：表达式用 `simplify(e1-e2)==0`；等式移项得 f1、f2，`simplify(f1-f2)==0` 或 `f2/f1` 为非零常数即等价。
- 找到**第一个**不等价步骤即停止（后续记 skipped），做错因分类。
- 解析失败的步骤记 `无法解析`（置信度 0.3），流程继续、基准不变。

**错因分类**（先规则后模型）：误区模式库（(a±b)² 漏交叉项 / 移项不变号 / 分配律漏乘）命中→概念混淆（0.85）；数字微调 ±1/±2/±3 后等价→计算失误（0.7）；兜底→审题遗漏（0.5）。之后由阿里云百炼模型复核；模型不可用时只保留本地规则判断，不拼接模拟回复。

**顽固误区**：同学生同知识点过去 N 天（默认 30）内已有错误 → `is_stubborn=true`。

**认证**：纯 mock，无密码。学生使用名册姓名+学号登录；教师仅选择任教学科，按学科确定教师身份。`POST /api/auth/login` 成功后返回 token（`mock-<id>`），后续请求带 `Authorization: Bearer <token>`。生产必须替换。

## 已知局限（诊断逻辑）

1. **等价性是数学等价，不是教学等价**：如 `x²=4x → x=4`（两边同除以 x，丢了 x=0 的解）在数学上不等价，会被判错——教学上可能算"步骤跳跃"，目前无法区分。
2. **模式库只覆盖三类常见误区**（平方展开漏交叉项、移项不变号、分配律漏乘），且移项检测主要针对线性方程；其他误区走兜底「审题遗漏」（置信度 0.5），依赖教师复核/回标。
3. **算术偏差检测只试 ±1/±2/±3 的数字微调**，复杂口算错误（如 7×8=54）识别不到。
4. **隐式乘法与符号**：`2x` 可解析；但 `xy` 会被当作单个变量名；中文注释会被剥离，残留中文则整步记无法解析。
5. **订正判定**只验证"订正内容与出错前一步等价"，不检查订正是否真正修复了错误类型。
6. 当前部署不启用 Mock 作文评分；作文评分使用阿里云百炼模型，API Key 未配置或调用失败会返回模型错误。
7. SQLite 已启用 WAL，并会等待数据库锁最多 30 秒，以减少读写竞争；但 SQLite 仍然一次只能有一个写事务。写并发较高时应切换到 PostgreSQL（表结构已兼容，改 `DATABASE_URL` 即可）。
