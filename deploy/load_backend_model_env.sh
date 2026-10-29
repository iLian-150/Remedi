# Source this file from the BaoTa Python project's environment-file setting.
# Keep credentials in /remedi/.env; command substitution stays in shell memory.
set +x
_remedi_model_exports="$(python - "${REMEDI_MODEL_ENV_FILE:-/remedi/.env}" <<'PY'
import re
import shlex
import sys

try:
    from dotenv import dotenv_values

    values = dotenv_values(sys.argv[1], interpolate=False)
    selected = {
        key: value for key, value in values.items()
        if re.fullmatch(r"(?:LLM|DASHSCOPE)_[A-Z0-9_]+", key) and value is not None
    }
    required = (
        "DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL",
        "DASHSCOPE_MODEL", "DASHSCOPE_VISION_MODEL",
    )
    if any(not selected.get(key, "").strip() for key in required):
        raise ValueError("incomplete model configuration")
except Exception as exc:
    # Never include exception text or configuration values in the startup log.
    print(f"Remedi model environment could not be loaded ({type(exc).__name__})", file=sys.stderr)
    sys.exit(1)

for key, value in selected.items():
    print(f"export {key}={shlex.quote(value)}")
PY
)" || exit 1
eval "$_remedi_model_exports"
unset _remedi_model_exports
