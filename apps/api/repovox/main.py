import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from repovox.analysis.transport import GitHubHTTP
from repovox.api.routes import router
from repovox.auth.session import DevelopmentSessions
from repovox.core.config import Settings
from repovox.core.errors import DomainError
from repovox.core.services import Services
from repovox.db.database import make_engine, verify_role
from repovox.services.jobs import Jobs
from repovox.services.projects import Projects

logger = logging.getLogger("repovox")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False
SAFE_DB_CODES = {
    "not_found": 404,
    "unauthorized": 401,
    "idempotency_conflict": 409,
    "monthly_quota": 429,
    "queue_quota": 429,
    "admission_rate": 429,
    "authentication_rate": 429,
    "terminal_conflict": 409,
    "invalid_retry": 409,
}


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()  # type: ignore[call-arg]
    engine = make_engine(config.database_url.get_secret_value())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        verify_role(engine, "rv_app")
        yield
        engine.dispose()

    app = FastAPI(title="RepoVox API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    app.state.engine = engine
    app.state.sessions = DevelopmentSessions(engine, config)
    app.state.projects = Projects(engine)
    token = config.github_token.get_secret_value() if config.github_token else None
    app.state.jobs = Jobs(engine, config.fixtures, config.analysis, GitHubHTTP(token))
    app.state.services = Services(config, app.state.sessions, app.state.projects, app.state.jobs)

    def error(request: Request, code: str, status: int) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": code, "request_id": request.state.request_id}}, status_code=status
        )

    @app.middleware("http")
    async def correlation(request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = (
            supplied if re.fullmatch(r"[a-zA-Z0-9-]{1,64}", supplied) else str(uuid4())
        )
        start = time.monotonic()
        body = bytearray()
        # Enforce streaming size too; Content-Length can be missing or dishonest.
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16384:
                break
        if len(body) > 16384:
            response: Response = error(request, "request_too_large", 413)
        else:
            request._body = bytes(body)
            try:
                response = await call_next(request)
            except Exception:
                response = error(request, "internal_error", 500)
        response.headers["x-request-id"] = request.state.request_id
        response.headers["cache-control"] = "no-store"
        response.headers["x-content-type-options"] = "nosniff"
        logger.info(
            json.dumps(
                {
                    "event": "http",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "severity": "INFO",
                    "service": "api",
                    "environment": config.environment,
                    "version": "0.1.0",
                    "request_id": request.state.request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000, 2),
                }
            )
        )
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error(request, exc.code, exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error(request, "invalid_request", 422)

    @app.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # Only known procedure codes cross HTTP; never return SQL, params or server details.
        code = str(exc.orig).splitlines()[0]
        return error(
            request,
            code if code in SAFE_DB_CODES else "dependency_unavailable",
            SAFE_DB_CODES.get(code, 503),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "alive", "version": "0.1.0"}

    @app.get("/ready")
    def ready() -> dict[str, Any]:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except DBAPIError:
            raise DomainError("database_unavailable", 503) from None
        return {"status": "ready", "generation_available": False, "environment": config.environment}

    app.include_router(router)
    return app
