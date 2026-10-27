import asyncio
import json
import logging
import time
import traceback
import uuid
from urllib.parse import urlsplit

from starlette.responses import JSONResponse

from app.core.exceptions import BridgeError

logger = logging.getLogger("ai_web_bridge")


class RequestMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started, request_id, status = time.perf_counter(), uuid.uuid4().hex, 500
        response_started = False
        scope.setdefault("state", {})

        async def tracked_send(message):
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message["headers"].append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > self.max_bytes:
                            scope["state"]["error_type"] = "CONTENT_TOO_LARGE"
                            await JSONResponse(
                                BridgeError(
                                    "CONTENT_TOO_LARGE", "Request body exceeds the size limit."
                                ).payload(),
                                status_code=413,
                            )(scope, receive, tracked_send)
                            return
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await JSONResponse(
                    BridgeError("REQUEST_TIMEOUT", "Request body timed out.").payload(), status_code=408
                )(scope, receive, tracked_send)
                return
            delivered = False

            async def buffered_receive():
                nonlocal delivered
                if delivered:
                    return await receive()
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            await self.app(scope, buffered_receive, tracked_send)
        except Exception as exc:
            # Last-resort boundary: details are logged, never exposed to API callers.
            logger.error(
                json.dumps(
                    {
                        "request_id": request_id,
                        "error_type": type(exc).__name__,
                        "stack": traceback.format_tb(exc.__traceback__),
                    }
                )
            )
            if not response_started:
                await JSONResponse(
                    BridgeError("INTERNAL_ERROR", "An unexpected server error occurred.").payload(),
                    status_code=500,
                )(scope, receive, tracked_send)
            else:
                raise
        finally:
            result = scope["state"].get("result")
            fields = {
                "request_id": request_id,
                "status": status,
                "total_duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "error_type": scope["state"].get("error_type"),
            }
            if result:
                fields.update(
                    hostname=urlsplit(result.request.get("url") or "").hostname,
                    returned_size=result.optimization.returned_characters,
                    response_size=result.optimization.raw_bytes,
                    reduction_percent=result.optimization.reduction_percent,
                )
                fields.update(
                    {
                        key: value
                        for key, value in (result.metadata or {}).items()
                        if key in {"cached", "fetch_method", "fetch_duration_ms", "parse_duration_ms"}
                    }
                )
            logger.info(json.dumps(fields))
