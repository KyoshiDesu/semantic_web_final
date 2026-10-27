"""The local JSON API (/api) and the frontend's files (/) in one process.

Local only: no login, so the server binds 127.0.0.1, refuses foreign Host headers (DNS rebinding) and refuses writes
from other origins (any web page could otherwise POST a form here, e.g. to start a paid LLM grading job).
"""
import logging
import sqlite3
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from autograde import db, gold, importer, io, kg, llm
from autograde.api.routes import courses, grading, imports, questions, semantic

WEB = io.ROOT / "web"
HOSTS = ["localhost", "127.0.0.1"]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CODES = {400: "bad_request", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 409: "conflict",
         413: "too_large", 422: "invalid", 503: "busy"}
ROUTERS = [courses.router, questions.router, imports.router, grading.router, semantic.router]
log = logging.getLogger("uvicorn.error")


def error(status, message, details=None, headers=None):
    return JSONResponse({"error": CODES.get(status, "internal" if status >= 500 else "error"), "message": message,
                         "details": details or []}, status_code=status, headers=headers)


def startup():
    db.connect(create=True).close()  # a new install starts in the app; SchemaVersionError stops the server
    kg.sync_ontology()
    db.interrupt_running_jobs()


@asynccontextmanager
async def lifespan(app):
    startup()
    yield


def create_app():
    app = FastAPI(title="AutoGrade-RDF", lifespan=lifespan)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        if isinstance(exc.detail, list):
            return error(exc.status_code, "invalid input", exc.detail, exc.headers)
        return error(exc.status_code, str(exc.detail), headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error(422, "invalid request", [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()])

    @app.exception_handler(importer.ImportDataError)
    @app.exception_handler(gold.GoldError)
    async def invalid_data(request, exc):
        return error(422, "invalid input", str(exc).split("; "))

    @app.exception_handler(importer.QuestionExistsError)
    async def question_exists(request, exc):
        return error(409, str(exc))

    @app.exception_handler(sqlite3.IntegrityError)
    async def duplicate(request, exc):
        return error(409, f"already exists ({exc})")

    @app.exception_handler(kg.KGBusyError)
    async def busy(request, exc):
        return error(503, str(exc), headers={"Retry-After": "2"})

    @app.exception_handler(llm.LLMUnavailable)
    async def no_llm(request, exc):
        return error(400, str(exc))

    @app.exception_handler(Exception)
    async def internal(request, exc):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return error(500, str(exc))

    @app.middleware("http")
    async def same_origin_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in SAFE_METHODS and origin is not None \
                and urlsplit(origin).netloc != request.headers.get("host"):
            return error(403, "cross-origin request refused")
        return await call_next(request)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=HOSTS)
    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")  # last: /api and /docs match first
    return app
