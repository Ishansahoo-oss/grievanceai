"""
GrievanceAI FastAPI application entrypoint.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import init_db

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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all so every unhandled error still returns {"error": "..."}"""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/health")
def health():
    return {"ok": True}


from app.routers import intake  # noqa: E402

app.include_router(intake.router)

# Remaining routers are added incrementally as they're built.
# from app.routers import citizen, admin
# app.include_router(citizen.router)
# app.include_router(admin.router)
