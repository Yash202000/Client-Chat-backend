from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.database import Base, engine, SessionLocal
from app.models import role, permission, contact, comment # Import new models
from app.core.config import settings
from app.api.v1.main import api_router, websocket_router
from app.api.v1.endpoints import ws_updates, comments
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_updates.router, prefix="/ws") # New company-wide updates
app.include_router(comments.router, prefix="/api/v1/comments")


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

@app.get("/api/v1/agents/{agent_id}/widget-settings", response_model=schemas_widget_settings.WidgetSettings)
def read_widget_settings(agent_id: int, db: Session = Depends(get_db)):
    return widget_settings_service.get_widget_settings(db, agent_id=agent_id)

@app.put("/api/v1/agents/{agent_id}/widget-settings", response_model=schemas_widget_settings.WidgetSettings)
def update_widget_settings(agent_id: int, widget_settings: schemas_widget_settings.WidgetSettingsUpdate, db: Session = Depends(get_db)):
    return widget_settings_service.update_widget_settings(db, agent_id=agent_id, widget_settings=widget_settings)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)