# Remedi

多学科智能作业批改与学习诊断系统，包含教师端、学生端、AI 助手、作业发布与批改、错题订正、学习档案和学科知识库。

## 核心功能

- 教师可在「AI 批改」中按作业和学生查看逐题结果，并为每位学生的每份作业撰写或编辑一条教师评语。
- 学生从「作业 → 查看批改结果」进入后，可先在作业标题下查看已发布评语，再查看逐题结果。
- 评语按作业和学生关联保存；未发布的评语不会显示给学生。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Vue Router、Pinia
- 后端：Python 3.11+、FastAPI、SQLAlchemy
- 数据：SQLite（可配置 PostgreSQL）、Milvus 学科向量检索
- 模型：通过环境变量配置阿里云百炼等模型服务；密钥不得提交到 Git

## 本地开发

在仓库根目录创建 Python 虚拟环境并安装后端依赖：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
```

另开终端启动前端：

```bash
cd frontend
npm ci
npm run dev
```

Vite 默认把 `/api` 请求代理到 `http://localhost:8000`。详见 [前端说明](frontend/README.md) 与 [后端说明](backend/README.md)。

## 本地验证

前端构建和现有 smoke 脚本见[验证入口](docs/validation.md)。仓库级开发与部署约定见 [AGENTS.md](AGENTS.md)。

## 文档

- [接口契约](docs/api-contract.md)
- [数据表设计与当前表清单](docs/schema-design.md)
- [学科 RAG 与 Milvus 本地配置](docs/milvus-rag.md)
- [校园服务台业务流程](docs/campus-service-workflow.md)
- [前端设计规范](docs/frontend-design-guidelines.md)
- [项目技术资料索引](docs/技术资料/README.md)：项目概览、工作流、架构和数据接口索引。
- [v0.5 历史规格](docs/v0.5-spec.md)
