"""
Development of Enterprise Workflow Platform with Decision Automation System — Backend Entrypoint
===============================================================
Run locally with:
    uvicorn app.main:app --reload --port 8000

Interactive API docs available at:
    http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.services.seed_users import seed_demo_users
from app.services.monitoring_scheduler import start_monitoring, stop_monitoring

# Import models so SQLAlchemy's metadata knows about every table before create_all()
from app.models import dev_collab  # noqa: F401
from app.models import incident  # noqa: F401
from app.models import memory  # noqa: F401
from app.models import tool_execution  # noqa: F401
from app.models import monitoring  # noqa: F401
from app.models import user  # noqa: F401
from app.models import notification  # noqa: F401
from app.models import enterprise  # noqa: F401
from app.models import workflow  # noqa: F401
from app.models import workflow_engine  # noqa: F401

from app.routers import (
    admin_routes,
    auth_routes,
    chat_routes,
    dev_collab_routes,
    incident_routes,
    monitoring_routes,
    system_routes,
    websocket_routes,
    tool_routes,
    workflow_routes,
)
from app.services.workflow_orchestrator_service import seed_workflow_definitions
from app.services.sla_watchdog_scheduler import start_sla_watchdog, stop_sla_watchdog

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} ({settings.ENV})")
    await init_db()
    await seed_demo_users()
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await seed_workflow_definitions(db)
    await start_monitoring()
    await start_sla_watchdog()
    yield
    await stop_sla_watchdog()
    await stop_monitoring()
    logger.info("Shutting down.")


app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-agent system coordinating Dev-Collaboration conflict "
                "prevention and AIOps incident response under one Decision Engine.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Accept any localhost/127.0.0.1 port in development — Vite may auto-pick
    # a different port (5173, 5174, ...) if the default is already in use.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(chat_routes.router)
app.include_router(dev_collab_routes.router)
app.include_router(incident_routes.router)
app.include_router(monitoring_routes.router)
app.include_router(system_routes.router)
app.include_router(websocket_routes.router)
app.include_router(tool_routes.router)
app.include_router(workflow_routes.router)
app.include_router(admin_routes.router)


@app.get("/")
async def root():
    return {
        "message": f"{settings.APP_NAME} is running.",
        "docs": "/docs",
        "modules": ["dev-collaboration", "aiops-incident-response"],
        "phases": {
            "A": "real-github-integration",
            "B": "background-server-monitoring",
            "C": "multi-user-login",
            "D": "mcp-tool-layer",
            "M4": "workflow-orchestration-monitoring-dashboards",
        },
        "monitoring_enabled": settings.MONITORING_ENABLED,
        "mcp": "python -m app.mcp_server",
    }
