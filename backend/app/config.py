# Remedi 后端配置：全部从环境变量读取，带默认值，开箱即用。
import os


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


class Settings:
    # 数据库连接串。默认 SQLite 文件 ./remedi.db（相对 backend/ 运行目录）。
    # 切 PostgreSQL 时改为 postgresql+psycopg2://user:pass@host/db 即可，代码零改动。
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./remedi.db")

    # 百炼统一提供文字、视觉、向量与重排模型；凭证缺失时明确报错。
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "bailian").strip().lower()
    if LLM_PROVIDER in {"dashscope", "aliyun"}:
        LLM_PROVIDER = "bailian"
    LLM_TIMEOUT_SECONDS: int = _get_int("LLM_TIMEOUT_SECONDS", 120)

    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "").strip()
    DASHSCOPE_BASE_URL: str = os.getenv(
        "DASHSCOPE_BASE_URL", "").strip().rstrip("/")
    DASHSCOPE_MODEL: str = os.getenv("DASHSCOPE_MODEL", "kimi-k3").strip()
    DASHSCOPE_VISION_MODEL: str = os.getenv("DASHSCOPE_VISION_MODEL", "qwen3-vl-plus").strip()

    # 旧提供方环境变量仅保留迁移兼容，当前调用使用上方百炼配置。
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Cloudflare Workers AI 配置（OpenAI 兼容接口）。
    # 未配置 CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN 时请求明确失败，不使用 Mock。
    CLOUDFLARE_ACCOUNT_ID: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    CLOUDFLARE_MODEL: str = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8").strip()
    # 视觉模型直接处理拍照诊断与转写，不经独立 OCR 服务。
    CLOUDFLARE_VISION_MODEL: str = os.getenv(
        "CLOUDFLARE_VISION_MODEL", "@cf/qwen/qwen3.8-27b").strip()

    # Milvus 可独立用 Docker 部署；未设置 URI 时仅启用本地 BM25 检索。
    RAG_MILVUS_URI: str = os.getenv("RAG_MILVUS_URI", "").strip()
    RAG_MILVUS_TOKEN: str = os.getenv("RAG_MILVUS_TOKEN", "").strip()
    RAG_MILVUS_COLLECTION: str = os.getenv(
        "RAG_MILVUS_COLLECTION", "remedi_subject_knowledge_qwen37_flash").strip()
    RAG_EMBEDDING_MODEL: str = os.getenv("RAG_EMBEDDING_MODEL", "qwen3.7-text-embedding-flash").strip()
    RAG_EMBEDDING_DIMENSIONS: int = _get_int("RAG_EMBEDDING_DIMENSIONS", 1024)
    RAG_TIMEOUT_SECONDS: int = max(1, min(_get_int("RAG_TIMEOUT_SECONDS", 8), 30))
    RAG_RERANK_MODEL: str = os.getenv("RAG_RERANK_MODEL", "qwen3.7-text-rerank").strip()
    RAG_RERANK_TIMEOUT_SECONDS: int = max(1, min(_get_int("RAG_RERANK_TIMEOUT_SECONDS", 10), 30))

    # 拍照上传的图片本地存放目录（默认 backend/uploads/）。只存文件，不落库。
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"),
    )

    # 顽固误区判定窗口（天）：同一学生同一知识点 N 天内重复出错即记顽固
    STUBBORN_WINDOW_DAYS: int = _get_int("STUBBORN_WINDOW_DAYS", 30)

    # CORS。默认放行所有来源方便前端 dev server 联调；生产请收紧。
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    # Teacher-entered assignment deadlines are local wall times in this zone.
    APP_TIMEZONE: str = (
        os.getenv("APP_TIMEZONE", "Asia/Shanghai").strip() or "Asia/Shanghai"
    )

    APP_VERSION: str = "0.13.362"


settings = Settings()
