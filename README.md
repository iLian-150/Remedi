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

模型统一使用阿里云百炼，配置通过环境变量传入（见 `backend/app/config.py`）。服务器 `/remedi/.env` 的模型参数如下，API Key 按当前要求先留空，演示数据初始化保持关闭：

```dotenv
SEED_DEMO_DATA=false
LLM_PROVIDER=bailian
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
DASHSCOPE_VISION_MODEL=qwen3-vl-plus
RAG_EMBEDDING_MODEL=text-embedding-v4
RAG_EMBEDDING_DIMENSIONS=1024
```

默认接口为北京地域；使用新加坡地域账号时，将 `DASHSCOPE_BASE_URL` 改为 `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`。API Key 留空不影响网站、数据库和健康检查启动；资料检索先使用 BM25。补齐对应地域的有效 Key 后，才能使用 AI 问答、图片识别和向量化，再在学科知识库中重建检索索引。模型未配置或调用失败时会明确报错，不生成模拟答案。

## MVP 范围

In：数学计算/化简/解方程分步诊断、错因疑似三分类＋置信度、教师一键纠错、学习记忆、重复错误识别、个人错误档案、班级统计、英语作文轻量五维评分。
Out：手写 OCR（接口预留）、证明题语义判分、二次验证自动触发、知识修复率完整指标、外部推送 —— 进二期。
