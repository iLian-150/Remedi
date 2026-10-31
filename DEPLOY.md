# Remedi 生产部署指南

## 当前生产架构

生产目录为 `/remedi`。应用进程由宝塔管理，Docker 仅托管向量检索依赖：

```text
浏览器 → 宝塔 Nginx（前端静态文件，端口 5001，/api 反代）
                         → 宝塔 Python 项目（FastAPI，127.0.0.1:5000）
                                               → SQLite / Milvus
Docker Compose：Milvus + etcd + MinIO
```

不要按早期文档使用 `docker compose up -d --build` 构建或重启前后端容器。宝塔 Python 项目的环境变量由 `/remedi/deploy/load_backend_model_env.sh` 从服务器本地 `/remedi/.env` 读取；该文件含密钥，不得提交或复制到文档。

## 日常发布

在本地仓库根目录先提交并推送 `main`。若 GitHub 上已有新提交，先拉取并适配本地改动，解决冲突后再推送；不要强推。推送成功后，在 Windows PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe deploy/pull_server.py
```

脚本通过 SSH 在服务器 `/remedi` 拉取 `origin/main`，并核对服务器检出的提交。也可以按项目部署约定先 SSH 登录服务器，再运行：

```bash
cd /remedi
git pull --ff-only origin main
git rev-parse HEAD
```

核对服务器 HEAD 与 GitHub `main` 一致后，再按实际改动部署受影响的组件。

## 按改动部署组件

### 仅 Markdown 文档

拉取并核对提交即可，不需要构建前端或重启服务。

### 前端代码

在服务器构建静态文件：

```bash
cd /remedi/frontend
npm ci
npm run build
```

构建产物写入 `frontend/dist`，由宝塔 Nginx 提供。通常不需要重启 Nginx；若 Nginx 配置也有改动，先检查配置再按变更要求 reload。

### 后端代码

在宝塔面板重启 Remedi Python 项目，使新代码生效。检查服务健康：

```bash
curl -fsS http://127.0.0.1:5000/api/health
```

若健康检查失败，先查看宝塔 Python 项目日志和对应组件错误；不要因此重启无关服务。

### Milvus / Compose 配置

只有向量服务或其 Compose 配置变更时，才在服务器 `/remedi` 操作相应容器。先查看状态和配置差异，按 [Milvus 与 RAG 指南](docs/milvus-rag.md)更新所需服务。不要使用未限定服务名的 `docker compose down`，也不要重建应用容器。

## 首次部署核对

- 宝塔 Nginx 站点根目录指向 `/remedi/frontend/dist`，并将 `/api` 代理到 `http://127.0.0.1:5000`。
- 宝塔 Python 项目使用项目配置的虚拟环境，工作目录为 `/remedi/backend`，ASGI 应用入口为 `app.main:app`。
- Python 项目从 `/remedi/deploy/load_backend_model_env.sh` 加载模型和 RAG 环境变量。
- `/remedi/.env` 由服务器本地管理，权限为 `600`，不要覆盖或删除。
- Docker Compose 只启动 Milvus、etcd、MinIO；数据库、上传目录和向量集合都应保留。
- 应用健康检查通过后，再从浏览器验证教师端和学生端。

## 相关文档

- [后端运行与配置](backend/README.md)
- [前端开发与构建](frontend/README.md)
- [API 契约](docs/api-contract.md)
- [Milvus 部署、数据迁移和维护](docs/milvus-rag.md)
