# 学科 RAG 与 Milvus 部署

学科资料和可追溯片段由 Remedi 数据库保存。Milvus 提供稠密向量召回，与本地 BM25 候选按排名融合。向量仅写入 Milvus，不在应用目录或业务数据库保存本地向量。Milvus、百炼向量模型超时或索引暂不可用时，资料检索继续使用本地 BM25。

## 镜像与 ARM64

默认固定 `milvusdb/milvus:v2.6.25`，Python 依赖为 `pymilvus>=2.6.17,<2.7`，遵循 [Milvus 2.6.25 发布兼容表](https://github.com/milvus-io/milvus/releases/tag/v2.6.25)。etcd 使用 `quay.io/coreos/etcd:v3.5.25`；MinIO 使用 [Milvus 官方 Compose](https://github.com/milvus-io/milvus/blob/master/deployments/docker/standalone/docker-compose.yml)采用的 `milvusdb/minio:RELEASE.2024-12-18T13-15-44Z`。

2026-10-22 核查官方 registry metadata，这三个固定 tag 都包含原生 `linux/arm64`，可以在 `aarch64` 服务器直接运行，无需 QEMU 或设置 `platform: linux/amd64`。Milvus/MinIO 的 [Docker Hub](https://hub.docker.com/r/milvusdb/milvus/tags?name=v2.6.25) 和 [etcd manifest](https://quay.io/repository/coreos/etcd?tab=tags&tag=v3.5.25) 可用于再次核对；旧 `minio/minio` 的历史 tag 不作为部署依赖。

## 配置统一放在 .env

部署目录为 `/remedi`。文字、视觉、向量化统一使用阿里云百炼；配置放在服务器本地 `.env`，不要提交真实凭证：

```dotenv
COMPOSE_PROJECT_NAME=remedi
COMPOSE_FILE=docker-compose.yml:docker-compose.milvus.yml
WEB_PORT=5001
API_PORT=5000
BUILD_NETWORK=host
SEED_DEMO_DATA=false
LLM_PROVIDER=bailian
DASHSCOPE_API_KEY=
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
DASHSCOPE_VISION_MODEL=qwen3-vl-plus
RAG_MILVUS_URI=http://milvus:19530
RAG_MILVUS_COLLECTION=remedi_subject_knowledge_bailian_v4
RAG_EMBEDDING_MODEL=text-embedding-v4
RAG_EMBEDDING_DIMENSIONS=1024
RAG_TIMEOUT_SECONDS=8
RAG_MINIO_ROOT_USER=remedi-rag
RAG_MINIO_ROOT_PASSWORD=replace-with-a-long-random-password
```

`COMPOSE_FILE` 的冒号分隔方式适用于 Linux 服务器。配置后，每次运行普通 `docker compose up -d --build` 都会合并 Milvus overlay。不要在后续发布时去掉该变量或仅指定基础文件，否则 API 容器会失去 Milvus 环境配置。所有凭证通过 `.env` 提供，无需另建包含秘密的 override。

`BUILD_NETWORK=host` 使镜像构建阶段使用宿主机的网络与 DNS，适配本服务器构建桥接网络无法解析域名的情况；API、前端和向量服务运行时仍使用项目 Docker 内网。无需修改全局 Docker 配置或系统 DNS。

`SEED_DEMO_DATA=false` 跳过启动时的演示数据生成及其模型请求，不删除已有数据。当前服务器按用户要求将 `DASHSCOPE_API_KEY` 留空；数据库健康检查不实例化模型，网站、后端和 BM25 资料检索可独立启动。AI 问答及向量化在补齐可用凭证后启用，不会返回模拟答案。旧 Cloudflare 配置不再参与运行。

后续在 `/remedi/.env` 填写 `DASHSCOPE_API_KEY`，再执行：

```bash
cd /remedi
docker compose up -d --force-recreate api
```

之后在教师知识库点击“重建检索索引”，将模型未配置期间导入的资料同步到 Milvus。模型名称、向量库和 MinIO 参数已经预置，无需将真实令牌加入 Git 或镜像。默认地址对应北京地域；若账号使用新加坡等地域，按[百炼兼容接口文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)修改 `DASHSCOPE_BASE_URL`，API Key 须与地域匹配。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `RAG_MILVUS_URI` | 应用默认空；overlay 默认 `http://milvus:19530` |
| `RAG_MILVUS_TOKEN` | 空；外部实例启用鉴权时填写对应 token |
| `RAG_MILVUS_COLLECTION` | `remedi_subject_knowledge_bailian_v4` |
| `RAG_EMBEDDING_MODEL` | `text-embedding-v4` |
| `RAG_EMBEDDING_DIMENSIONS` | `1024`；入库与查询一致 |
| `RAG_TIMEOUT_SECONDS` | `8`；单次网络操作超时，上限 30 秒 |
| `DASHSCOPE_API_KEY` | 百炼 API Key，当前留空，用户后续填写 |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `DASHSCOPE_MODEL` / `DASHSCOPE_VISION_MODEL` | `qwen-plus` / `qwen3-vl-plus` |
| `RAG_MINIO_ROOT_USER` / `RAG_MINIO_ROOT_PASSWORD` | overlay 必填；独立 MinIO 账户和密码 |
| `RAG_MILVUS_IMAGE` | `milvusdb/milvus:v2.6.25` |
| `RAG_ETCD_IMAGE` | `quay.io/coreos/etcd:v3.5.25` |
| `RAG_MINIO_IMAGE` | `milvusdb/minio:RELEASE.2024-12-18T13-15-44Z` |

向量化使用[百炼 OpenAI 兼容 Embeddings 接口](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)，`text-embedding-v4` 每批最多 10 个片段，显式指定 1024 维，按响应 `index` 恢复输入顺序并验证数量、维数和数值。集合保存片段 ID、文档 ID、学科、模型和向量，使用 COSINE / AUTOINDEX。[服务端检索](https://milvus.io/api-reference/pymilvus/v2.6.x/MilvusClient/Vector/search.md)同时过滤学科和向量模型；业务层还会核验片段仍存在于当前学科。更换模型或维数时更换集合名并重新索引，避免混用向量空间。

## 启动与数据位置

```bash
cd /remedi
docker compose config --quiet
docker compose up -d milvus
bash deploy/enable_project_network.sh
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:9091/healthz
```

overlay 将持久化目录全部绑定到 `/remedi/data`：

| 宿主机目录 | 容器目标 | 用途 |
| --- | --- | --- |
| `/remedi/data/api` | API `/data` | 业务数据库与上传文件 |
| `/remedi/data/etcd` | etcd `/etcd` | Milvus 元数据 |
| `/remedi/data/minio` | MinIO `/minio_data` | 向量对象存储 |
| `/remedi/data/milvus` | Milvus `/var/lib/milvus` | 向量服务数据 |

基础 Compose 中历史 `remedi-data` 命名卷定义保留，overlay 按相同目标 `/data` 覆盖 API 挂载；不要删除历史卷。已有业务数据迁移到此部署目录时，应先确认 `/remedi/data/api` 包含需要保留的数据，再启动 API。

MinIO 镜像自带的 `/data` 默认卷也绑定到 `/remedi/data/minio`；服务实际使用 `/minio_data`，两处均在项目目录内，避免运行中容器额外创建匿名数据卷。

Milvus 19530 和健康检查 9091 只绑定宿主机 `127.0.0.1`；etcd、MinIO 不发布宿主机端口。API 启动不依赖 Milvus 就绪，启动期间可使用 BM25。第一次建集合或加载超过超时后可重试。普通基础部署未启用 overlay 时不启动 Milvus；宿主机运行后端时可设置 `RAG_MILVUS_URI=http://127.0.0.1:19530`。

前端访问 `http://129.153.206.96:5001`，后端访问 `http://129.153.206.96:5000`，接口文档位于后端 `/docs`。公网入站只需放行 TCP 5001、5000，SSH 运维沿用 22；无需开放 Milvus、etcd 或 MinIO 的公网端口。前端通过 Nginx 转发 `/api` 到 API 容器内 8000 端口。

## 本地修改后的发布

本地虚拟环境验证通过后，提交并普通 push 到 GitHub main，再拉取服务器代码：

```powershell
git push origin main
.\.venv\Scripts\python.exe deploy/pull_server.py
```

仓库为私有仓库，脚本从本地 Git 凭证管理器读取凭证，经 SSH 标准输入仅供本次 `git pull --ff-only origin main` 使用；凭证不写入服务器文件、Git 配置或日志。脚本校验服务器没有已跟踪文件改动，并核对服务器提交与本地提交一致。

随后在服务器执行：

```bash
cd /remedi
docker compose up -d --build
docker compose ps
docker compose exec -T api python smoke_live_rag.py
```

API 容器中的 `python` 来自 `/app/.venv`；无需向服务器宿主机的系统 Python 安装依赖。真实链路验收脚本会新增一条临时资料，检查向量入库、混合检索与权限后自动删除。

本服务器曾出现 `FORWARD` 默认 DROP 且 Docker 跳转缺失的情况。`deploy/enable_project_network.sh` 只按 `remedi_default` 的 bridge 和 IPv4 网段添加幂等转发规则，允许项目出站、内部通信、已有连接返回及已发布的 HTTP 端口；不修改默认策略、NAT、其他项目规则或 `/etc` 文件。服务器重启或重建项目网络后，先运行 `docker compose up -d milvus`、该脚本，再启动完整项目。

## 将已有资料同步到 Milvus

使用具有对应学科权限的教师账号调用：

```http
POST /api/teacher/knowledge/math/reindex
Authorization: Bearer <教师登录令牌>
```

该操作重新同步指定学科全部资料。对教师负责的每个学科各调用一次；学科代码为 `chinese`、`math`、`english`、`politics`、`history`、`physics`、`chemistry`、`geography`、`biology`。新增或删除资料时同步对应索引。

资料列表中的 `vector_enabled` 仅表示配置了 Milvus 地址。新增或重建响应中的 `vector_status=ready` 表示同步成功，`disabled` 表示未启用，`pending` 表示本次同步失败；同时检查 `warnings`。失败时保留资料，恢复服务后再次重建。

重建目前使用同步请求，大规模资料可能超过客户端或代理超时。可以重试：按固定片段 ID 执行幂等 upsert，不会重复创建资料，并保留片段 ID 和 PDF 页码。

试查检索来源：

```http
POST /api/teacher/knowledge/math/search
Authorization: Bearer <教师登录令牌>
Content-Type: application/json

{"query":"一次函数的斜率表示什么？","limit":4}
```

## 检查与维护

启用后上传数学资料、重建数学索引，用资料中的问题查询，再用其他学科查询，确认没有跨学科引用。删除资料后查询其独有内容，确认不再引用；Milvus 暂停时确认问答回退 BM25，恢复后重建失败的索引。

```bash
cd /remedi
docker compose logs --tail=100 milvus milvus-etcd milvus-minio
docker compose up -d --build
```

常规更新保留 `.env` 的 `COMPOSE_FILE` 和整个 `data/`；不要使用 `down -v` 清理业务或索引数据。外部 Milvus 可直接配置 URI/token，首次 overlay 部署使用容器网络和 loopback 端口；若开启 Milvus 鉴权，同时配置服务端鉴权和 `RAG_MILVUS_TOKEN`。

## 本地契约验证

```bash
cd backend
python smoke_rag_milvus.py
```

脚本使用真实 PyMilvus SDK 构造 schema 和索引参数，模拟全部网络调用，验证维数、批次、学科/模型过滤、连接/集合复用和异常处理。它不连接真实 Milvus 或百炼，不能替代服务启动后的集成验证。
