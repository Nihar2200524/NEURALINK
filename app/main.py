import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.routes import router
from app.core.config import Settings
from app.core.exceptions import BridgeError
from app.core.logging import RequestMiddleware
from app.services.manager import RequestManager


def create_app(settings: Settings | None = None, manager: RequestManager | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        logging.getLogger("httpx").setLevel(logging.WARNING)
        app.state.manager = manager or RequestManager(settings)
        yield
        await app.state.manager.close()

    app = FastAPI(title="AI Web Bridge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestMiddleware, max_bytes=settings.max_request_bytes)
    app.include_router(router)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            BridgeError("INVALID_REQUEST", "The request could not be handled.").payload(),
            status_code=exc.status_code,
        )

    @app.exception_handler(BridgeError)
    async def bridge_error(request: Request, exc: BridgeError):
        request.state.error_type = exc.code
        return JSONResponse(exc.payload(), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request validation failed.",
                    "details": {"fields": [list(e["loc"]) for e in exc.errors()]},
                }
            },
            status_code=422,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "ai-web-bridge"}

    return app


app = create_app()
