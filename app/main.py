from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.core.database import Base, engine
from app.core.config import settings
from app.api.v1.main import api_router, websocket_router
from app.core.dependencies import get_db
from app.services import widget_settings_service
from app.schemas import widget_settings as schemas_widget_settings

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
app.include_router(websocket_router, prefix="/ws") # Include WebSocket router separately

@app.get("/")
async def read_root():
    return {"message": "AgentConnect backend is running"}


from app.core.database import SessionLocal
from app.services import company_service, user_service, agent_service
from app.schemas import company as schemas_company, user as schemas_user, agent as schemas_agent

@app.on_event("startup")
def on_startup():
    db = SessionLocal()
    try:
        # Check if a default company exists, if not, create one
        default_company = company_service.get_companies(db, limit=1)
        if not default_company:
            print("Creating default company...")
            company = company_service.create_company(db, schemas_company.CompanyCreate(name="Default Company"))
        else:
            company = default_company[0]

        # Check if a default user exists, if not, create one
        default_user = user_service.get_users(db, company.id, limit=1)
        if not default_user:
            print("Creating default user...")
            user_service.create_user(db, schemas_user.UserCreate(email="user@example.com", password="password123"), company_id=company.id)

        # Check if a default agent exists, if not, create one
        default_agent_list = agent_service.get_agents(db, company.id, limit=1)
        if not default_agent_list:
            print("Creating default agent...")
            agent = agent_service.create_agent(db, schemas_agent.AgentCreate(name="Default Agent", welcome_message="Hello! How can I help you?", prompt="You are a helpful assistant. You have access to a set of tools. Use them when necessary to answer the user's questions. When asked a math question, use the 'calculate_sum' tool."), company_id=company.id)
        else:
            agent = default_agent_list[0]
        
        # Check if default widget settings exist, if not, create them
        default_widget_settings = widget_settings_service.get_widget_settings(db, agent_id=agent.id)
        if not default_widget_settings:
            print("Creating default widget settings...")
            widget_settings_service.create_widget_settings(db, schemas_widget_settings.WidgetSettingsCreate(agent_id=agent.id))


    finally:
        db.close()

@app.get("/api/v1/agents/{agent_id}/widget-settings", response_model=schemas_widget_settings.WidgetSettings)
def read_widget_settings(agent_id: int, db: Session = Depends(get_db)):
    return widget_settings_service.get_widget_settings(db, agent_id=agent_id)

@app.put("/api/v1/agents/{agent_id}/widget-settings", response_model=schemas_widget_settings.WidgetSettings)
def update_widget_settings(agent_id: int, widget_settings: schemas_widget_settings.WidgetSettingsUpdate, db: Session = Depends(get_db)):
    return widget_settings_service.update_widget_settings(db, agent_id=agent_id, widget_settings=widget_settings)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
