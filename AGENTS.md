# Remedi 操作流程

## 开发与线上发布

Remedi 的常规发布流程是：本地修改 → 推送到 GitHub → 服务器拉取代码 → Docker Compose 重新构建并启动。

### 本地修改

1. 每次开始处理仓库任务时，在编辑任何文件前检查 `git status --short --branch`，并确认是否已同步 GitHub 最新 `main`。在 `main` 分支执行 `git pull --ff-only origin main`；确认命令成功且本地提交与 `origin/main` 一致后，才开始修改。
2. 若当前不在 `main`、工作区有未提交改动、本地与远端提交不一致或拉取失败，先检查差异并妥善保留现有修改，再安全同步；不得丢弃用户改动、重置服务器或强推远端。Windows 上 GitHub 连接失败时，检查系统代理并仅对本次 Git 命令临时使用，不要擅自改写全局代理配置。
3. 修改前后都检查 `git status` 和 `git diff`，确认只包含本次相关改动，并保留用户已有的未提交修改。
4. 用户已要求本项目的每次代码或配置修改都走完整发布流程，并在服务器成功部署、检查通过后再结束。推送到 GitHub 的 `main` 分支时使用普通 push，不要强推；push 成功并核对远端提交号后，才可操作服务器。
5. 每次提交的标题和正文（提交理由）统一使用简体中文，准确说明本次改动目的。

### 更新服务器

- 主机：`root@129.153.206.96`（ARM64）
- 仓库目录：`/remedi`；只操作该目录和本项目 Docker 资源，不修改其他目录或项目。
- 模型凭证及 Compose 参数统一放服务器 `/remedi/.env`，权限 `600`；不要打印或提交真实凭证。该文件通过 `COMPOSE_FILE=docker-compose.yml:docker-compose.milvus.yml` 启用完整服务，后续发布保留此配置。
- Python 使用虚拟环境：本地 `.venv`，后端 Docker 镜像内 `/app/.venv`；不要向宿主机全局 Python 安装项目依赖。
- SSH 私钥位于本地用户目录的 `.ssh/codex_deploy_ed25519`；不要复制、打印或提交私钥。

推送成功后，通过 SSH 在服务器执行：

```bash
cd /remedi
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
```

在 Windows PowerShell 中连接服务器：

```powershell
ssh.exe -i "$env:USERPROFILE\.ssh\codex_deploy_ed25519" -o IdentitiesOnly=yes root@129.153.206.96
```

部署后检查容器状态；若容器未正常运行，查看 `docker compose logs --tail=100` 并处理构建或启动错误，再反馈实际结果。

### 数据与发布安全

- 新服务器所有业务与向量数据保留在 `/remedi/data/{api,etcd,minio,milvus}`；不要运行 `docker compose down -v` 或删除数据。旧部署命名卷 `remedi-data` 同样不得删除。
- 不要覆盖服务器上用户自行配置的环境变量、密钥或数据文件。
- `docker-compose.yml` 是生产部署定义；涉及服务、端口、卷或构建配置的修改，部署后应核对容器状态和日志。
- 若 push、SSH、`git pull` 或 Docker 构建失败，停止后续发布步骤并报告具体错误，不要用强推、重置服务器改动或删除数据的方式绕过。
