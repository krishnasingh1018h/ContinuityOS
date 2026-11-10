from fastapi import APIRouter

from app.routes.auth import router as auth_router
from app.routes.claims import router as claims_router
from app.routes.handover import router as handover_router
from app.routes.projects import router as projects_router
from app.routes.reconstruction import router as reconstruction_router
from app.routes.sources import router as sources_router
from app.routes.workflow import router as workflow_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(projects_router)
router.include_router(sources_router)
router.include_router(reconstruction_router)
router.include_router(claims_router)
router.include_router(workflow_router)
router.include_router(handover_router)
