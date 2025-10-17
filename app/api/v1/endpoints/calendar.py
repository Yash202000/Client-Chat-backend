from fastapi import APIRouter

router = APIRouter()

# All Google OAuth logic has been moved to the central /api/v1/google endpoint.
# This file is kept for any future calendar-specific (non-auth) endpoints.