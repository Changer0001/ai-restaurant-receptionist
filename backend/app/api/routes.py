"""
API Routes

Main router that includes all API endpoints.
"""

from fastapi import APIRouter

# Import sub-routers as we build them
# from app.api.endpoints import auth, restaurants, calls, reservations

router = APIRouter()

# Include sub-routers
# router.include_router(auth.router, tags=["Authentication"])
# router.include_router(restaurants.router, prefix="/restaurants", tags=["Restaurants"])
# router.include_router(calls.router, prefix="/calls", tags=["Calls"])
# router.include_router(reservations.router, prefix="/reservations", tags=["Reservations"])

# Placeholder endpoints for MVP foundation


@router.get("/status")
async def api_status():
    """API status endpoint."""
    return {"status": "operational", "version": "0.1.0"}
