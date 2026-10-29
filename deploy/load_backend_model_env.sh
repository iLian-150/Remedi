# Source this file from the BaoTa Python project's environment-file setting.
# Keep credentials in /remedi/.env; command substitution stays in shell memory.
set +x
_remedi_model_exports="$(python - "${REMEDI_MODEL_ENV_FILE:-/remedi/.env}" <<'PY'
import re
import shlex
import sys

try:
    from dotenv import dotenv_values

    with open(sys.argv[1], encoding="utf-8-sig") as source:
        values = dotenv_values(stream=source, interpolate=False)
    selected = {
        key: value for key, value in values.items()
        if re.fullmatch(r"(?:LLM|DASHSCOPE|RAG)_[A-Z0-9_]+", key) and value is not None
    }
    # This loader is only used by the host backend. Preserve the Compose value
    # on disk and custom remote endpoints, adapting only our Docker default.
    if selected.get("RAG_MILVUS_URI", "").rstrip("/") == "http://milvus:19530":
        selected["RAG_MILVUS_URI"] = "http://127.0.0.1:19530"
except Exception as exc:
    # Never include exception text or configuration values in the startup log.
    print(f"Remedi model environment could not be loaded ({type(exc).__name__}); continuing with process configuration", file=sys.stderr)
    selected = {}

for key, value in selected.items():
    print(f"export {key}={shlex.quote(value)}")
PY
)" || _remedi_model_exports=""
eval "$_remedi_model_exports"
unset _remedi_model_exports
