# 学科 RAG 与 Milvus 本地配置

> 本项目采用本地开发流程：前端由 Vite 启动，后端由本地 Python 虚拟环境启动。需要向量检索时，Docker Compose 只启动 Milvus、etcd 和 MinIO。

学科资料和可追溯片段由 Remedi 数据库保存。Milvus 提供稠密向量召回，与本地 BM25 候选按排名融合，再使用 `Qwen3-Reranker-0.6B` 重排。向量仅写入 Milvus，不在应用目录或业务数据库保存本地向量。Milvus、AI Ping 向量模型超时或索引暂不可用时，资料检索继续使用本地 BM25；模型重排失败时使用本地重排，并返回不含凭证或上游响应的安全警告。

## 持久化导入与 OCR

文件上传完成后，`POST /api/teacher/knowledge/{subject}/import` 返回 `202` 与任务对象。后台工作线程独立处理，浏览器关闭弹窗、切页或刷新不影响任务。`GET /api/teacher/knowledge/import-jobs` 查询有权限学科的任务；`POST /api/teacher/knowledge/import-jobs/{id}/retry` 重试失败任务，`.../{id}/dismiss` 保存关闭通知。完成和失败通知不自动消失。

原始资料与页级检查点由 `KNOWLEDGE_IMPORT_DIR` 指定，不通过 `/api/uploads` 静态目录公开。文件按学科与 SHA256 去重，重复点击返回原任务，完成后重传不会重新 OCR。旧版没有文件摘要的历史资料保留，不按文件名猜测相同内容或删除。

文字层使用 PyMuPDF 直接提取；扫描页、乱码页和混合页面中的图片文字使用后端运行环境中的 Tesseract（`chi_sim+eng`）。复用 PyMuPDF 图片定位与矢量绘图聚类，只把相关图形区域交给 `GLM-5.3-Flash`；无法分区的扫描页在出现图形指示时使用压缩页面补充图形语义，不逐字转写整页。图形语义单独标记，模型不得补造未标注的关系。专用 OCR 不保证复杂公式完全准确，低可信度页面保留核对警告和原件。

OCR 与视觉网络请求最多同时执行 `RAG_OCR_WORKERS` 个页面（默认 2），PyMuPDF 渲染仅在导入线程执行。页面与区域完成后原子保存检查点；失败任务重试和进程重启复用已完成结果。任务进度来自后台成功页数和索引阶段。原文、片段、任务关联文档 ID 同一 SQL 事务提交后才同步 Milvus，向量故障返回待索引状态并继续提供 BM25。

## 九科学科集合与旧数据迁移

`RAG_MILVUS_COLLECTION` 现在是集合前缀。九科分别使用 `<前缀>_chinese`、`_math`、`_english`、`_politics`、`_history`、`_physics`、`_chemistry`、`_geography`、`_biology`，读写删除全部由后端固定学科映射选择集合，保留 `subject` 与当前向量模型过滤以及 SQL 片段归属校验。

升级后由后端维护脚本或后端 Python 环境调用 `subject_rag.migrate_subject_vectors(db, subject)`。该操作将旧共享集合中仍属于当前 SQL 文档的向量复制到对应集合，校验片段 ID、文档 ID、学科、向量模型和维度；不调用 OCR、不重新计算已有向量、不删除旧集合。检查返回的 `migrated`、`missing`、`vector_status`。若旧向量缺失，可针对该科重建索引，直接使用 SQL 中的片段，不重新 OCR。

## 本地服务版本

默认固定 `milvusdb/milvus:v2.6.25`，Python 依赖为 `pymilvus>=2.6.17,<2.7`，遵循 [Milvus 2.6.25 发布兼容表](https://github.com/milvus-io/milvus/releases/tag/v2.6.25)。etcd 使用 `quay.io/coreos/etcd:v3.5.25`；MinIO 使用 [Milvus 官方 Compose](https://github.com/milvus-io/milvus/blob/master/deployments/docker/standalone/docker-compose.yml)采用的 `milvusdb/minio:RELEASE.2024-12-18T13-15-44Z`。


## 本地配置

Docker Compose 从仓库根目录的 `.env` 读取 Milvus 容器所需的 MinIO 账户。该文件已被 Git 忽略：

```dotenv
RAG_MINIO_ROOT_USER=remedi-local
RAG_MINIO_ROOT_PASSWORD=replace-with-a-local-password
```

FastAPI 直接从启动进程的环境变量读取配置，不会自动读取 `.env`。PowerShell 中可在启动后端的终端设置本次会话变量：

```powershell
$env:RAG_MILVUS_URI = 'http://127.0.0.1:19530'
$env:LLM_API_KEY = '<本地 AI Ping API Key>'
$env:LLM_BASE_URL = 'https://aiping.cn/api/v1'
```

不要把真实 API Key 写入仓库文件。数据库和健康检查不依赖模型；向量服务不可用时仍可使用 BM25，重排失败时回退本地重排。

AI Ping 的 OpenAI 兼容地址为 `https://aiping.cn/api/v1`，向量化使用 `/embeddings`，重排使用 `/rerank`。问答、向量化和重排的可用性需分别通过实际调用验证。`RAG_API_KEY` 和 `RAG_BASE_URL` 留空时，后端复用 `LLM_API_KEY` 和 `LLM_BASE_URL`。

模型连接验证通过后，在教师知识库点击“重建检索索引”，将已有资料同步到新集合 `remedi_subject_knowledge_qwen3_embedding4b`。旧集合继续保留，不删除业务资料或历史向量。模型名称、向量库和 MinIO 参数已经预置，无需将真实令牌加入 Git 或镜像。

若显式配置 `Kimi-K3`，必须启用思考，工具调用轮次在本次请求内存中保留并回传 `reasoning_content`；`enable_thinking` 和 `preserve_thinking` 始终开启。隐藏推理不进入界面、SSE 回复正文或持久化聊天记录。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `RAG_MILVUS_URI` | 默认空；本地 Python 后端连接 Compose 时设置为 `http://127.0.0.1:19530` |
| `RAG_MILVUS_TOKEN` | 空；外部实例启用鉴权时填写对应 token |
| `RAG_MILVUS_COLLECTION` | `remedi_subject_knowledge_qwen3_embedding4b` |
| `RAG_EMBEDDING_MODEL` | `Qwen3-Embedding-4B` |
| `RAG_EMBEDDING_DIMENSIONS` | `1024`；入库与查询一致 |
| `RAG_TIMEOUT_SECONDS` | `8`；单次网络操作超时，上限 30 秒 |
| `RAG_RERANK_MODEL` | `Qwen3-Reranker-0.6B`；不可用时使用本地重排 |
| `RAG_RERANK_TIMEOUT_SECONDS` | `10`；模型重排请求超时（秒） |
| `LLM_API_KEY` | AI Ping API Key，仅通过本地后端进程环境变量提供 |
| `LLM_BASE_URL` | `https://aiping.cn/api/v1` |
| `RAG_API_KEY` / `RAG_BASE_URL` | 可留空，默认复用 LLM 凭证与地址 |
| `LLM_MODEL` / `LLM_VISION_MODEL` | `GLM-5.3-Flash` / `GLM-5.3-Flash` |
| `RAG_MINIO_ROOT_USER` / `RAG_MINIO_ROOT_PASSWORD` | overlay 必填；独立 MinIO 账户和密码 |
| `RAG_MILVUS_IMAGE` | `milvusdb/milvus:v2.6.25` |
| `RAG_ETCD_IMAGE` | `quay.io/coreos/etcd:v3.5.25` |
| `RAG_MINIO_IMAGE` | `milvusdb/minio:RELEASE.2024-12-18T13-15-44Z` |

向量化通过 AI Ping 的 OpenAI 兼容 Embeddings 接口调用 `Qwen3-Embedding-4B`，分批提交片段，显式指定 1024 维，按响应 `index` 恢复输入顺序并验证数量、维数和数值。集合保存片段 ID、文档 ID、学科、模型和向量，使用 COSINE / AUTOINDEX。[服务端检索](https://milvus.io/api-reference/pymilvus/v2.6.x/MilvusClient/Vector/search.md)同时过滤学科和向量模型；业务层还会核验片段仍存在于当前学科。更换模型或维数时更换集合名并重新索引，避免混用向量空间。

BM25 和 Milvus 的早期候选会在截断前按资料来源分散，避免一本长资料的相邻片段占满重排输入；Milvus 会先扩大召回窗口，候选分散只改变入选范围，不抬高原始排序分。BM25 还会将 LaTeX、Unicode 运算符和空格差异归一为公式 token，支持 `x+y=z` 这类短公式在向量不可用时召回，同时不把孤立数字当作证据。候选片段经 `Qwen3-Reranker-0.6B` 重排后再恢复父块并去重。模型超时或返回异常时，保留召回候选并使用本地重排；未配置凭证或将 `RAG_RERANK_MODEL` 设为空时，直接使用本地重排。试查响应中的 `rerank_mode=model|local` 表示实际重排方式，与 `retrieval_mode=bm25|hybrid` 分别报告。`warnings` 只返回安全说明，不回传密钥、请求头或原始上游错误。

删除资料时，先捕获其片段 ID 并提交本地删除，再仅清理这些确切的 Milvus 主键。SQLite 文档 ID 被后续上传复用时，延迟到达的旧删除不会误删新资料向量。清理失败仍保留安全警告，查询时继续核验 SQL 中片段的存活状态和学科。

## 本地启动与数据位置

```powershell
docker compose -f docker-compose.yml -f docker-compose.milvus.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.milvus.yml up -d milvus
docker compose -f docker-compose.yml -f docker-compose.milvus.yml ps milvus milvus-etcd milvus-minio
curl.exe --fail http://127.0.0.1:9091/healthz
```

该命令只启动 Milvus、etcd 和 MinIO，不启动 Compose 中的 `api` 或 `web`。向量数据保存在仓库根目录的 `data/`：

| 宿主机目录 | 用途 |
| --- | --- | --- |
| `data/etcd` | etcd 中的 Milvus 元数据 |
| `data/minio` | MinIO 中的向量对象存储 |
| `data/milvus` | Milvus 向量服务数据 |

本地业务数据库和上传目录由后端配置决定。保留 `data/` 中的向量服务数据；不要用 `docker compose down -v` 清理数据。

MinIO 镜像自带的 `/data` 默认卷也绑定到 `data/minio`；服务实际使用 `/minio_data`，避免运行中容器额外创建匿名数据卷。

Milvus `19530` 和健康检查 `9091` 只绑定本机回环地址；etcd、MinIO 不发布宿主机端口。后端启动不依赖 Milvus 就绪，启动期间可使用 BM25。首次建集合或加载超时后可重试。

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

检查响应的 `retrieval_mode`、`rerank_mode` 和 `warnings`，分别确认召回、重排和降级情况。`rerank_mode` 为新增字段，取 `model` 或 `local`；没有候选或模型重排未完成时，不会声称使用模型重排。

## 本地检查与维护

启用后上传数学资料、重建数学索引，用资料中的问题查询，再用其他学科查询，确认没有跨学科引用。删除资料后查询其独有内容，确认不再引用；Milvus 暂停时确认问答回退 BM25，恢复后重建失败的索引。重排模型不可用时，应得到 `rerank_mode=local` 与安全警告，仍可取得有来源的资料。

```bash
docker compose -f docker-compose.yml -f docker-compose.milvus.yml logs --tail=100 milvus milvus-etcd milvus-minio
```

外部 Milvus 可直接配置 URI/token；若开启 Milvus 鉴权，同时设置 `RAG_MILVUS_TOKEN`。

## 本地契约验证

```bash
cd backend
python smoke_rag_milvus.py
```

脚本使用真实 PyMilvus SDK 构造 schema 和索引参数，模拟全部网络调用，验证维数、批次、学科/模型过滤、连接/集合复用和异常处理。它不连接真实 Milvus 或 AI Ping，不能替代服务启动后的集成验证。
