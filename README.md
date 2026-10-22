# Remedi

Remedi 是一套多学科智能作业批改与学习诊断系统。批改只是入口：系统对数学解答题做分步等价验证、定位首次出错位置，对英语作文做五维诊断；在此之上建立纵向学习记忆——持续追踪每名学生的错误模式、订正效果与复发情况，区分偶发失误与顽固误区，并以知识修复率衡量真实掌握程度，最终反向输出班级认知断点与分层教学建议，让每个学生的问题都被看见。

Remedi is an intelligent homework grading and learning diagnosis system. Grading is just the entry point — it verifies math solutions step by step, diagnoses English essays across five dimensions, and builds a longitudinal learning memory that tracks each student's error patterns, corrections, and relapses, measuring true mastery by knowledge repair rate and feeding insights back into teaching.

## 仓库结构

```
remedi/
  backend/   Python 3.11 + FastAPI + SQLAlchemy + SQLite（表结构按 PG 兼容设计）
             sympy 符号等价验证；阿里云百炼模型接口
  frontend/  Vue 3 + TypeScript + Vite + Vue Router + Pinia + ECharts
             教师端 / 学生端双端同项目（views/teacher、views/student）
  docs/      接口契约（api-contract.md）、数据表设计（schema-design.md）
```

## 本地运行

当前服务器部署目标为 `129.153.206.96:/remedi`。Docker 服务包括 Remedi API、前端 Nginx、Milvus、etcd 与 MinIO；前端端口为 `5001`，后端端口为 `5000`。配置统一保存在服务器 `/remedi/.env`，数据位于 `/remedi/data/`。Python 依赖安装在虚拟环境中：本地使用 `backend/.venv`，后端容器使用 `/app/.venv`。完整配置、首次启动和后续发布见 [部署说明](docs/milvus-rag.md)。

```bash
# 后端
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed.py            # 演示数据（可选）
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev               # 开发模式（vite 代理 /api 到 localhost:8000）
npm run build             # 生产构建 → dist/
```

模型统一通过阿里云百炼调用，配置通过环境变量传入（见 `backend/app/config.py`）。文字模型使用 `Kimi-K3`，视觉模型使用 `qwen3-vl-plus`，向量化和重排分别使用 `qwen3.7-text-embedding-flash`、`qwen3.7-text-rerank`。以下为服务器 `/remedi/.env` 的配置示例，真实 API Key 仅保存在服务器，不写入示例或提交到 Git：

```dotenv
SEED_DEMO_DATA=false
LLM_PROVIDER=bailian
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=kimi-k3
DASHSCOPE_VISION_MODEL=qwen3-vl-plus
RAG_MILVUS_COLLECTION=remedi_subject_knowledge_qwen37_flash
RAG_EMBEDDING_MODEL=qwen3.7-text-embedding-flash
RAG_EMBEDDING_DIMENSIONS=1024
RAG_RERANK_MODEL=qwen3.7-text-rerank
RAG_RERANK_TIMEOUT_SECONDS=10
```

`DASHSCOPE_BASE_URL` 必须使用百炼控制台提供的工作空间专属 APIHost，并带上 `/compatible-mode/v1`；示例中的 `<workspace-id>` 和北京地域均需按实际账号替换。模型可用性通过实际请求验证。凭证或模型不可用不影响网站、数据库和健康检查启动；向量化不可用时使用 BM25，模型重排调用失败时使用本地重排，并返回安全警告。有效配置启用后，在学科知识库中重建索引，将资料写入新集合；保留旧集合与业务数据。

`Kimi-K3` 始终启用思考，工具调用轮次按协议临时回传模型的推理字段；这些字段不进入界面、SSE 回复正文或持久化聊天记录。AI 问答调用失败时会明确报错，不生成模拟答案。

## MVP 范围

In：数学计算/化简/解方程分步诊断、错因疑似三分类＋置信度、教师一键纠错、学习记忆、重复错误识别、个人错误档案、班级统计、英语作文轻量五维评分。
Out：手写 OCR（接口预留）、证明题语义判分、二次验证自动触发、知识修复率完整指标、外部推送 —— 进二期。
