# Remedi 操作流程

## 开发与线上发布

Remedi 当前部署方式：前端由宝塔 Nginx 提供静态文件（5001），后端由宝塔 Python 项目运行（5000），Milvus、etcd、MinIO 使用本项目 Docker Compose。每次修改代码或配置后，必须重新部署所有直接受影响的组件；拉取代码不算部署完成。部署并检查通过后再结束任务，不要为了单个组件改动重启无关组件。

### 本地修改

1. 每次开始处理仓库任务时，在编辑任何文件前检查 `git status --short --branch`，并确认是否已同步 GitHub 最新 `main`。在 `main` 分支执行 `git pull --ff-only origin main`；确认命令成功且本地提交与 `origin/main` 一致后，才开始修改。
2. 若当前不在 `main`、工作区有未提交改动或本地与远端提交不一致，先检查差异并妥善保留现有修改。若 GitHub `main` 已有新提交，必须把远端改动安全合并/变基到本地、解决冲突并重新构建验证，再普通 push；不得因分叉直接放弃，也不得丢弃用户改动、重置服务器或强推远端。Windows 上 GitHub 连接失败时，检查系统代理并仅对本次 Git 命令临时使用；也可使用已连接且有写权限的 GitHub 通道完成同等的快进更新，不要擅自改写全局代理配置。

   - Windows 代理排查细节：Git for Windows 不会自动继承当前用户的 WinINET 代理。若浏览器或 `api.github.com` 可访问、但 Git 直连 `github.com:443` 超时/重置，检查注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings` 的 `ProxyEnable` 和 `ProxyServer`，确认代理端口可用后，用 `git -c http.proxy=http://<代理主机:端口> <命令>` 临时执行 `pull`、`push` 或 `ls-remote`。本机已验证过的代理为 `127.0.0.1:7890`，但每次仍应以当前系统代理配置为准；不要把代理写入全局或仓库 Git 配置。先用 `git -c http.proxy=... ls-remote origin refs/heads/main` 验证，再执行同步/推送。
3. 修改前后都检查 `git status` 和 `git diff`，确认只包含本次相关改动，并保留用户已有的未提交修改。
4. 用户要求每次代码或配置修改都重新部署相应部分：前端改动重新构建并发布前端；后端改动更新后端代码、按需安装依赖并重启宝塔 Python 项目；Milvus/etcd/MinIO 或 Compose 配置改动只重新部署受影响的 Docker 服务；Nginx 配置改动须测试配置并重载 Nginx。跨端改动要部署所有受影响部分。必须把本次改动推送到 GitHub 的 `main` 并确认远端提交号；若推送因远端更新被拒，先安全同步并适配远端改动后再普通 push，禁止强推。只有确认 push 成功后，才操作服务器 `/remedi` 执行 `git pull`，核对服务器提交号，再部署受影响组件。
5. 每次提交的标题和正文（提交理由）统一使用简体中文，准确说明本次改动目的。

### 更新服务器

- 主机：`root@129.153.206.96`（ARM64）
- 仓库目录：`/remedi`。服务器操作限于该仓库、本项目 Docker 资源，以及宝塔中 Remedi 自己的前端站点和后端 Python 项目；不修改其他目录或项目，不改系统默认防火墙策略或其他项目规则。
- 模型凭证及 Compose 参数统一放服务器 `/remedi/.env`，权限 `600`；不要打印或提交真实凭证。保留其中 `COMPOSE_FILE=docker-compose.yml:docker-compose.milvus.yml` 配置，但当前只通过 Compose 管理 Milvus、etcd、MinIO；不要因此启动 Docker 前后端。
- 用户当前指定阿里云百炼：`LLM_PROVIDER=bailian`，文字 `Kimi-K3`、视觉 `qwen3-vl-plus`、向量 `qwen3.7-text-embedding-flash`（1024 维）、重排 `qwen3.7-text-rerank`（超时 10 秒）。用户已提供 API Key，仅保存到服务器 `/remedi/.env`，不得打印、提交或复制进文档；示例 Key 保持为空。`DASHSCOPE_BASE_URL` 必须使用用户确认的控制台工作空间专属 APIHost（如 `https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，工作空间和地域按账号确定）；未做实际调用验证时不得宣称模型可用。
- 学科向量集合使用 `RAG_MILVUS_COLLECTION + "_" + subject`（默认前缀 `remedi_subject_knowledge_qwen37_flash`），九科独立集合。旧同名前缀共享集合保留，只通过 `migrate_subject_vectors` 显式迁移有效片段，不删除旧向量或业务数据；变更向量模型后重建索引。向量不可用时回退 BM25；模型重排不可用时回退本地重排，响应保留 `rerank_mode=model|local`，警告不得含凭证或原始上游响应。保留 `SEED_DEMO_DATA=false`；模型缺失不得阻止网站、数据库或健康检查启动。
- 知识库文档上传后返回持久任务，原件与逐页检查点保存在 `/remedi/data/api/knowledge-imports`，不得放到公开的 uploads 静态目录。扫描文字复用 Tesseract 专用 OCR，Qwen-VL 仅按需解析图形；重试复用缓存，不能恢复整书逐页远程转写。任务须可查询、重启恢复、按学科和 SHA256 防重复，通知由用户显式关闭。
- `Kimi-K3` 必须启用思考并在工具调用循环中按协议回传模型推理字段；仅在本次请求内存中保留，不将隐藏推理发送到界面、SSE 正文或持久化聊天记录。不得恢复旧 Cloudflare 凭证或擅自切换用户指定模型。
- Python 使用虚拟环境：本地 `.venv`，生产后端使用宝塔 Remedi Python 项目选定的虚拟环境；不要向宿主机全局 Python 安装项目依赖。依赖变化时只在该项目环境安装 `backend/requirements.txt` 中的依赖。
- 前端发布在 `5001`，构建产物目录为 `/remedi/frontend/dist`；后端由宝塔 Python 项目运行在 `127.0.0.1:5000`。当前不要通过 Docker Compose 部署或重启前后端。Milvus 端口仅绑定本机，etcd/MinIO 不发布公网端口。
- 服务器若重启或重建网络，先启动 Milvus，再运行 `bash deploy/enable_project_network.sh` 检查本项目转发规则；不改系统默认防火墙策略或其他项目规则。
- 私有仓库拉取可在本地虚拟环境运行 `python deploy/pull_server.py`，经 SSH 临时传递当前 Git 凭证供服务器执行 `git pull --ff-only origin main`，不将 GitHub 凭证持久化到服务器。
- SSH 私钥位于本地用户目录的 `.ssh/codex_deploy_ed25519`；不要复制、打印或提交私钥。

推送成功后，在本地虚拟环境运行 `python deploy/pull_server.py`，通过 SSH 临时传递 Git 凭证，在服务器 `/remedi` 执行快进拉取并核对提交号；不要把 GitHub 凭证保存到服务器。

然后只重新部署本次改动涉及的部分：

- **前端代码或构建配置**：在 `/remedi/frontend` 使用项目锁文件安装依赖并执行生产构建（`npm ci`、`npm run build`），确认 `/remedi/frontend/dist` 已更新；宝塔 Nginx 继续提供该目录。仅静态文件变化不需要重启后端。
- **后端代码或依赖**：依赖有变化时，使用宝塔 Remedi Python 项目选定的虚拟环境安装 `/remedi/backend/requirements.txt`；然后在宝塔重启该 Python 项目，并确认 `curl -fsS http://127.0.0.1:5000/api/health` 成功。仅后端变化不启动 Docker 前后端容器。
- **Nginx 站点配置**：先运行 `nginx -t`，成功后再通过宝塔重载 Nginx；不要覆盖其他站点配置。
- **Milvus、etcd、MinIO 或其 Compose 配置**：只启动或重建受影响的本项目服务，并检查 `docker compose ps` 与对应日志。不要为前后端代码改动执行完整 `docker compose up -d --build`。

在 Windows PowerShell 中连接服务器：

```powershell
ssh.exe -i "$env:USERPROFILE\.ssh\codex_deploy_ed25519" -o IdentitiesOnly=yes root@129.153.206.96
```

部署后检查对应组件：前端请求返回正常页面、后端健康检查通过、Nginx 配置测试通过，或受影响的 Docker 服务健康。若组件未正常运行，查看该组件日志并处理构建或启动错误，再反馈实际结果。

### 数据与发布安全

- 新服务器所有业务与向量数据保留在 `/remedi/data/{api,etcd,minio,milvus}`；不要运行 `docker compose down -v` 或删除数据。旧部署命名卷 `remedi-data` 同样不得删除。
- 不要覆盖服务器上用户自行配置的环境变量、密钥或数据文件。
- Docker Compose 仅用于当前由 Docker 管理的 Milvus、etcd、MinIO 等服务；涉及这些服务、端口、卷或构建配置的修改，部署后应核对容器状态和日志。前后端由宝塔分别管理，不因 Compose 文件中存在相关定义就启动 Docker 前后端。
- 若网络/认证导致无法读取或写入 GitHub，或 SSH、服务器拉取、依赖安装、前端构建、后端重启、健康检查或相关 Docker 构建失败，停止依赖该步骤的后续发布并报告具体错误；远端分叉本身不是停止理由，应先安全同步和解决冲突。不要用强推、重置服务器改动或删除数据的方式绕过。

## 前端开发硬性规则

- 实现前先检查 `frontend/package.json`、锁文件、`frontend/src/components/` 和 `frontend/src/assets/style.css`，优先复用已有依赖、共享组件、图标和设计 token。
- 如果现有依赖或共享组件能够正确满足需求，必须复用；禁止因此手写一套替代组件或重复实现已有交互行为。弹窗、菜单、下拉、提示、日期选择、图表等常见能力尤其要先检查已有实现。
- 只有现有依赖和组件确实无法满足功能、可访问性或性能要求时，才考虑自实现。新增依赖前先排查同类依赖，说明必要性；优先选源码可审阅、维护活跃、版本可锁定的成熟库，禁止引入职责重复的库或运行时 CDN 代码。
- 延续 Remedi 统一设计语言：复用 `frontend/src/assets/style.css` 中的颜色、间距、圆角、阴影和排版 token，优先复用 `AppIcon` 及现有共享组件；不要为单页另造一套视觉体系或散落新的固定色值。
- 页面默认不加辅助标签、标题副说明、卡片解释句、重复提示或装饰性文案。优先用分组、对齐、留白、层级、图标和状态表达信息；可见文字只保留完成操作、区分选项、理解状态/结果/错误所必需的内容。
- 只有缺少说明会导致用户无法完成操作、容易输错、误解重要状态，或无法恢复错误时，才添加简短的就地说明；不得把标题、字段、按钮已经表达的信息再解释一遍。表单仍须有清晰标签和可访问名称，精简文案不能以牺牲可访问性为代价。
- 详细规则以 `docs/frontend-design-guidelines.md` 为准；修改前端时应一并遵守。
