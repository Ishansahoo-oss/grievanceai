"""
GrievanceAI FastAPI application entrypoint.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db import init_db
from app.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger("grievanceai")

app = FastAPI(title="GrievanceAI", version="0.1.0")

# CORS: allow all origins for now (SIH prototype). Tighten before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Every HTTPException (404, 400, 409, etc.) must return {"error": "..."}"""
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic/body validation failures (422) also follow {"error": "..."}"""
    first = exc.errors()[0] if exc.errors() else None
    message = f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}" if first else "Invalid request"
    return JSONResponse(status_code=422, content={"error": message})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all so every unhandled error still returns {"error": "..."}"""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.on_event("startup")
def on_startup():
    init_db()
    start_scheduler(interval_minutes=5)


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"ok": True}


from app.routers import admin, citizen, intake  # noqa: E402

app.include_router(intake.router)
app.include_router(citizen.router)
app.include_router(admin.router)
