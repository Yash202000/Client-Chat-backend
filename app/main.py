from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import os

from app.core.database import Base, engine, SessionLocal
from app.models import role, permission, contact, comment # Import new models
from app.core.config import settings
from app.api.v1.main import api_router, websocket_router
from app.api.v1.endpoints import ws_updates, comments, gmail, google, published, ai_images, ai_chat, object_detection
from app.core.dependencies import get_db
from app.services import tool_service, widget_settings_service
from app.schemas import widget_settings as schemas_widget_settings
from create_tool import create_api_call_tool

# Create all database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
)

# CORS middleware to allow frontend to connect
# Note: Widget needs to be accessible from any origin
# Parse CORS origins from comma-separated string in settings
cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_updates.router, prefix="/ws") # New company-wide updates
app.include_router(comments.router, prefix="/api/v1/comments")
app.include_router(gmail.router, prefix="/api/v1/gmail")
app.include_router(google.router, prefix="/api/v1/google")
app.include_router(published.router, prefix="/api/v1/published")
app.include_router(ai_images.router, prefix="/api/v1/ai-images", tags=["ai-images"])
app.include_router(ai_chat.router, prefix="/api/v1/ai-chat", tags=["ai-chat"])
app.include_router(object_detection.router, prefix="/api/v1/object-detection", tags=["object-detection"])

# Mount static files for serving the widget
widget_static_path = os.path.join(os.path.dirname(__file__), "static", "widget")
if os.path.exists(widget_static_path):
    app.mount("/widget", StaticFiles(directory=widget_static_path), name="widget")

@app.get("/")
async def read_root():
    return {"message": "AgentConnect backend is running"}


from app.initial_data import create_initial_data
from app.core.websockets import manager as websocket_manager

@app.on_event("startup")
def on_startup():
    create_initial_data()

@app.on_event("shutdown")
async def on_shutdown():
    print("Server is shutting down. Disconnecting all websocket clients...")
    await websocket_manager.disconnect_all()

if __name__ == "__main__":
    uvicorn.run(app, host=settings.HOST, port=settings.PORT, ws="websockets")