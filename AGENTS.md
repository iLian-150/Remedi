# Remedi 操作流程

## 开发与线上发布

Remedi 的常规发布流程是：本地修改 → 推送到 GitHub → 服务器拉取代码 → Docker Compose 重新构建并启动。

### 本地修改

1. 在当前仓库内完成用户要求的修改。
2. 检查 `git status` 和 `git diff`，确认只包含本次相关改动；保留用户已有的未提交修改。
3. 只有用户要求发布或部署时，才提交并推送改动。推送到 GitHub 的 `main` 分支时使用普通 push，不要强推。
4. 每次提交的标题和正文（提交理由）统一使用简体中文，准确说明本次改动目的。

### 更新服务器

- 主机：`root@47.112.10.119`
- 仓库目录：`/www/wwwroot/remedi`
- SSH 私钥位于本地用户目录的 `.ssh/codex_deploy_ed25519`；不要复制、打印或提交私钥。

推送成功后，通过 SSH 在服务器执行：

```bash
cd /www/wwwroot/remedi
git pull --ff-only origin main
docker compose up -d --build
docker compose ps
```

在 Windows PowerShell 中连接服务器：

```powershell
ssh.exe -i "$env:USERPROFILE\.ssh\codex_deploy_ed25519" -o IdentitiesOnly=yes root@47.112.10.119
```

部署后检查容器状态；若容器未正常运行，查看 `docker compose logs --tail=100` 并处理构建或启动错误，再反馈实际结果。

### 数据与发布安全

- 保留 Docker 命名卷 `remedi-data` 中的业务数据；更新时不要运行 `docker compose down -v` 或删除卷。
- 不要覆盖服务器上用户自行配置的环境变量、密钥或数据文件。
- `docker-compose.yml` 是生产部署定义；涉及服务、端口、卷或构建配置的修改，部署后应核对容器状态和日志。
- 若 push、SSH、`git pull` 或 Docker 构建失败，停止后续发布步骤并报告具体错误，不要用强推、重置服务器改动或删除数据的方式绕过。
