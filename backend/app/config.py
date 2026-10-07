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

    # LLM Provider：mock（默认，确定性，无需 key）| deepseek | cloudflare
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    # DeepSeek 配置。未配置 DEEPSEEK_API_KEY 时 DeepSeekProvider 自动降级为 Mock。
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "").strip()
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # Cloudflare Workers AI 配置（OpenAI 兼容接口）。
    # 未配置 CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN 时自动降级为 Mock。
    CLOUDFLARE_ACCOUNT_ID: str = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    CLOUDFLARE_API_TOKEN: str = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    CLOUDFLARE_MODEL: str = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3.8-27b").strip()
    # 视觉（拍照转写）模型。仅 CloudflareProvider 使用；其余 Provider 降级为 Mock 转写。
    CLOUDFLARE_VISION_MODEL: str = os.getenv(
        "CLOUDFLARE_VISION_MODEL", "@cf/meta/llama-3.2-11b-vision-instruct").strip()

    # 拍照上传的图片本地存放目录（默认 backend/uploads/）。只存文件，不落库。
    UPLOAD_DIR: str = os.getenv(
        "UPLOAD_DIR",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads"),
    )

    # 顽固误区判定窗口（天）：同一学生同一知识点 N 天内重复出错即记顽固
    STUBBORN_WINDOW_DAYS: int = _get_int("STUBBORN_WINDOW_DAYS", 30)

    # CORS。默认放行所有来源方便前端 dev server 联调；生产请收紧。
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "*")

    APP_VERSION: str = "0.6.2"


settings = Settings()
