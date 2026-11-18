"""Cross-cutting HTTP behaviour: request ids, access logs, and safe error responses.

Request id: every response carries X-Request-ID, and every access/error log line includes
it. A user reporting "it failed" can quote the id, and you find the exact log lines.
"""

import json
import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("app.http")

# A client may send its own id (useful when a frontend or gateway already has one), but
# it's untrusted input that ends up in logs: accept only short, plain ids.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class SafeJSONResponse(JSONResponse):
    """ensure_ascii=True escapes every non-ASCII character, so rendering can never fail,
    even on text that isn't valid Unicode."""

    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _is_valid_text(body: bytes) -> bool:
    """Valid UTF-8, and no lone UTF-16 surrogates hidden in JSON escapes."""
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if "\\u" not in text:  # fast path: no escape sequences at all
        return True
    try:
        json.dumps(json.loads(text), ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return False
    except ValueError:  # malformed JSON: let FastAPI answer with its normal 422
        return True
    return True


class RejectInvalidText:
    """Pure ASGI middleware: JSON bodies must be real text.

    JSON allows the escape for half of a UTF-16 pair on its own (a lone surrogate).
    Python accepts it as a string, but it can't be written as UTF-8: the database write
    or the response would crash with a 500. Rejected here with a clean 400 instead.
    (Pure ASGI, not @app.middleware, because the body must be read AND replayed.)
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        headers = dict(scope.get("headers") or [])
        if scope["type"] != "http" or b"json" not in headers.get(b"content-type", b""):
            await self.app(scope, receive, send)
            return
        chunks, more = [], True
        while more:
            message = await receive()
            if message["type"] != "http.request":  # client disconnected
                return
            chunks.append(message.get("body", b""))
            more = message.get("more_body", False)
        body = b"".join(chunks)
        if not _is_valid_text(body):
            response = SafeJSONResponse({"detail": "Request body must be valid UTF-8 text."}, status_code=400)
            await response(scope, receive, send)
            return

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def install_middleware(app: FastAPI) -> None:
    app.add_middleware(RejectInvalidText)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        """FastAPI's default 422 echoes the submitted values ("input"), so a rejected
        registration would send the PASSWORD back, into browser tools and proxy logs.
        Only where the problem is and what it is are returned."""
        errors = [{"loc": list(e.get("loc", ())), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                  for e in exc.errors()]
        return SafeJSONResponse({"detail": errors}, status_code=422)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        # Path only, never the query string or headers (they can carry tokens).
        logger.info("%s %s -> %d (%.0f ms) rid=%s", request.method, request.url.path,
                    response.status_code, elapsed_ms, request_id)
        return response

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        """Any bug -> a generic 500. Details go to the LOG, never to the client: stack
        traces and exception messages can reveal paths, SQL, or data."""
        request_id = getattr(request.state, "request_id", None) or uuid.uuid4().hex
        logger.error("Unhandled %s on %s %s rid=%s", type(exc).__name__, request.method,
                     request.url.path, request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error.", "request_id": request_id},
            headers={"X-Request-ID": request_id},
        )
