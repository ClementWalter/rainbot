"""RainBot Web API - FastAPI Application."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.api.auth import LoginRequest, Token, create_access_token
from src.api.routes import bookings, facilities, requests
from src.services.google_sheets import sheets_service

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(module)s - %(funcName)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("RainBot API starting up")
    yield
    logger.info("RainBot API shutting down")


app = FastAPI(
    title="RainBot API",
    description="Tennis court booking automation",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(requests.router, prefix="/api")
app.include_router(bookings.router, prefix="/api")
app.include_router(facilities.router, prefix="/api")


class UserInfo(BaseModel):
    """User information response."""

    id: str
    email: str
    name: Optional[str]
    subscription_active: bool
    carnet_balance: Optional[int]


@app.post("/api/auth/login", response_model=Token)
async def login(credentials: LoginRequest) -> Token:
    """
    Authenticate user with Paris Tennis credentials.

    For now, we validate against users in the Google Sheet.
    In the future, we could validate directly against Paris Tennis.
    """
    # Get all users from sheets
    users = sheets_service.get_all_users()

    # Find user by email
    user = next((u for u in users if u.email.lower() == credentials.email.lower()), None)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Check password (currently all users share the same Paris Tennis password from env)
    expected_password = os.getenv("PARIS_TENNIS_PASSWORD", "")
    if credentials.password != expected_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Create JWT token
    token = create_access_token(
        user_id=user.id,
        email=user.email,
        name=user.name,
    )

    return Token(access_token=token)


@app.get("/api/auth/me", response_model=UserInfo)
async def get_me(
    user_id: str = None,
) -> UserInfo:
    """Get current user information."""
    from fastapi import Depends

    from src.api.deps import get_current_user_id

    # This endpoint needs to be called with proper dependency injection
    # For now, return a placeholder
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)


# Health check
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "rainbot-api"}


# Serve static frontend files
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        """Serve frontend SPA."""
        # API routes are already handled by the router
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        # Try to serve the file directly
        file_path = FRONTEND_DIR / path
        if file_path.is_file():
            return FileResponse(file_path)

        # Fall back to index.html for SPA routing
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)

        raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
