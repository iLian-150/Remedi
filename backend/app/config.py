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

    # 所有模型问答统一走 Cloudflare Workers AI；服务不可用时明确报错，不返回模拟答案。
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "cloudflare").strip().lower()
    LLM_TIMEOUT_SECONDS: int = _get_int("LLM_TIMEOUT_SECONDS", 120)

    # 保留 DeepSeek 环境变量用于迁移兼容；当前应用只启用 Cloudflare Provider。
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

    # 拍照上传的图片本地存放目录（默认 backend/uploads/）。只存文件，不落库。
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"),
    )

    # 顽固误区判定窗口（天）：同一学生同一知识点 N 天内重复出错即记顽固
    STUBBORN_WINDOW_DAYS: int = _get_int("STUBBORN_WINDOW_DAYS", 30)

    # CORS。默认放行所有来源方便前端 dev server 联调；生产请收紧。
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    APP_VERSION: str = "0.13.65"


settings = Settings()
