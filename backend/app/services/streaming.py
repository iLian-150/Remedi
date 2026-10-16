"""Streaming response helpers that release synchronous model iterators."""
import anyio
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse


class ClosingStreamingResponse(StreamingResponse):
    """Close the source iterator after completion or client disconnect.

    Starlette adapts synchronous iterators for streaming, but its adapter does
    not close the original iterator when sending stops early. Model providers
    rely on iterator closure to release their upstream HTTP response.
    """

    def __init__(self, content, *args, **kwargs):
        self._source_iterator = content
        super().__init__(content, *args, **kwargs)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                close = getattr(self._source_iterator, "close", None)
                if close is not None:
                    await run_in_threadpool(close)
                else:
                    aclose = getattr(self._source_iterator, "aclose", None)
                    if aclose is not None:
                        await aclose()
