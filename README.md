# Remedi

多学科智能作业批改与学习诊断系统，包含教师端、学生端、AI 助手、作业发布与批改、错题订正、学习档案和学科知识库。

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

## 生产架构

生产环境运行在 `/remedi`：宝塔 Nginx 提供前端静态文件（端口 `5001`），宝塔 Python 项目运行 FastAPI（`127.0.0.1:5000`）；Docker Compose 仅运行 Milvus、etcd 和 MinIO。请按[部署指南](DEPLOY.md)发布，勿使用旧的全栈 Docker 部署方式。

## 文档

- [部署指南](DEPLOY.md)
- [接口契约](docs/api-contract.md)
- [数据表设计与当前表清单](docs/schema-design.md)
- [学科 RAG 与 Milvus](docs/milvus-rag.md)
- [前端设计规范](docs/frontend-design-guidelines.md)
- [v0.5 历史规格](docs/v0.5-spec.md)
