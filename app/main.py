from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import add_exception_handlers
from app.core.middleware import RequestIdMiddleware
from app.core.logging import setup_logging

# Setup logging
setup_logging()

app = FastAPI(
    title="BuildTrack API",
    version="1.0.0",
    description="Construction project tracking API",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)

# Exception handlers
add_exception_handlers(app)

# Import and include all routers
from app.modules.auth.router import router as auth_router
from app.modules.developers.router import router as developers_router
from app.modules.projects.router import router as projects_router
from app.modules.milestones.router import router as milestones_router
from app.modules.uploads.router import router as uploads_router
from app.modules.buyers.router import router as buyers_router
from app.modules.notifications.router import router as notifications_router
from app.modules.admin.router import router as admin_router
from app.modules.billing.router import router as billing_router
from app.modules.webhooks.router import router as webhooks_router
from app.modules.internal.router import router as internal_router
from app.modules.project_types.router import router as project_types_router
from app.modules.roles.router import router as roles_router
from app.modules.members.router import router as members_router
from app.modules.settings.router import router as settings_router

API_PREFIX = "/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(developers_router, prefix=API_PREFIX)
app.include_router(projects_router, prefix=API_PREFIX)
app.include_router(milestones_router, prefix=API_PREFIX)
app.include_router(uploads_router, prefix=API_PREFIX)
app.include_router(buyers_router, prefix=API_PREFIX)
app.include_router(notifications_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(billing_router, prefix=API_PREFIX)
app.include_router(webhooks_router, prefix=API_PREFIX)
app.include_router(internal_router, prefix=API_PREFIX)
app.include_router(project_types_router, prefix=API_PREFIX)
app.include_router(roles_router, prefix=API_PREFIX)
app.include_router(members_router, prefix=API_PREFIX)
app.include_router(settings_router, prefix=API_PREFIX)


@app.get("/healthz", tags=["health"])
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
async def readyz():
    return {"status": "ok"}
