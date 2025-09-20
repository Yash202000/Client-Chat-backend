
from sqlalchemy.orm import Session
from app.models import company as models_company
from app.schemas import company as schemas_company
from app.services import agent_service, role_service, tool_service, user_service, widget_settings_service
from app.schemas import company as schemas_company, user as schemas_user, agent as schemas_agent, widget_settings as schemas_widget_settings
from create_tool import create_api_call_tool

def get_company(db: Session, company_id: int):
    return db.query(models_company.Company).filter(models_company.Company.id == company_id).first()

def get_companies(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models_company.Company).offset(skip).limit(limit).all()

def create_company(db: Session, company: schemas_company.CompanyCreate):
    company = models_company.Company(name=company.name)
    db.add(company)
    db.commit()
    db.refresh(company)
    
    # Create roles for the company
    print("Creating default roles for the company...")
    role_service.create_initial_roles_for_company(db, company.id)
    
    # Get the Super Admin role
    super_admin_role = role_service.get_role_by_name(db, "Super Admin")

    # Check if a default user exists, if not, create one
    user_email = f'admin@{company.name}.com'
    default_user = user_service.get_user_by_email(db, user_email)
    if not default_user:
        print("Creating default admin user... ", user_email, "password")
        user_service.create_user(db, schemas_user.UserCreate(email=user_email, password="password"), company_id=company.id, role_id=super_admin_role.id, is_super_admin=True)
    else:
        # If user exists but has no role, assign super admin role
        # TODO: This should ideally not happen, change role to Admin with all CRUD permissions.
        user = default_user
        if not user.role_id:
            user.role_id = super_admin_role.id
        if not user.is_super_admin:
            user.is_super_admin = True
        db.commit()
        
    # Check if a default agent exists, if not, create one
    default_agent_list = agent_service.get_agents(db, company.id, limit=1)
    if not default_agent_list:
        print("Creating default agent...")
        prompt = (
            "You are a helpful assistant."
        )
        agent_create_data = schemas_agent.AgentCreate(
            name="Default Agent",
            welcome_message="Hello! How can I help you?",
            prompt=prompt,
            llm_provider="groq",
            model_name="llama-3.1-8b-instant"
        )
        agent = agent_service.create_agent(db, agent_create_data, company_id=company.id)
        # Create the api_call tool if it doesn't exist
        api_call_tool = tool_service.get_tool_by_name(db, "API Call", company.id)
        if not api_call_tool:
            print("Creating API Call tool...")
            create_api_call_tool(db, company.id)
    else:
        agent = default_agent_list[0]
    
    # Check if default widget settings exist, if not, create them
    default_widget_settings = widget_settings_service.get_widget_settings(db, agent_id=agent.id)
    if not default_widget_settings:
        print("Creating default widget settings...")
        widget_settings_service.create_widget_settings(db, schemas_widget_settings.WidgetSettingsCreate(agent_id=agent.id))

    return company
