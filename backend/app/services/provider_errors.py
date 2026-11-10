"""Model failure diagnostics without response bodies, prompts or credentials."""
from logging import Logger


def _http_status(error: BaseException) -> int | None:
    seen = set()
    while error is not None and id(error) not in seen and len(seen) < 8:
        seen.add(id(error))
        status = getattr(error, "status_code", None)
        if status is None:
            status = getattr(getattr(error, "response", None), "status_code", None)
        if type(status) is int and 100 <= status <= 599:
            return status
        error = error.__cause__ or error.__context__
    return None


def log_model_failure(logger: Logger, message: str, error: Exception, *context_args) -> None:
    """Only pass trusted message templates and application IDs as context."""
    logger.warning(
        message + " (error=%s, http_status=%s)",
        *context_args, type(error).__name__, _http_status(error),
    )
