"""
API Routes

Main router that includes all API endpoints.
"""

from fastapi import APIRouter

from app.api.endpoints import auth, faqs, hours, restaurants

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
router.include_router(restaurants.router, prefix="/restaurants", tags=["Restaurants"])
router.include_router(hours.router, prefix="/restaurants", tags=["Restaurant Hours"])
router.include_router(faqs.router, prefix="/restaurants", tags=["Restaurant FAQs"])

# Added in later phases:
# router.include_router(calls.router, prefix="/calls", tags=["Calls"])
# router.include_router(reservations.router, tags=["Reservations"])


@router.get("/status", tags=["Health"])
async def api_status():
    """API status endpoint."""
    return {"status": "operational", "version": "0.1.0"}
