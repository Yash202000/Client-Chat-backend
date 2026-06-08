from app.core.database import SessionLocal
from app.services import company_service, user_service, agent_service, role_service, tool_service, widget_settings_service
from app.schemas import company as schemas_company, user as schemas_user, agent as schemas_agent, widget_settings as schemas_widget_settings
from app.models.subscription_plan import SubscriptionPlan
from create_tool import create_api_call_tool

# ─── Subscription plan feature sets ──────────────────────────────────────────
# Starter: conversations + agents + basic CRM (no deals/accounts) + support basics
_STARTER_FEATURES = (
    "conversations,agents,knowledge_base,tools,widget_designer,"
    "contacts,leads,forms,team_chat,calendar,drive,"
    "settings,billing,team_management"
)
# Growth: unlock the pipeline (deals, accounts), outreach (campaigns), automation,
#         analytics, social, AI chat, ticketing, booking, and all CRM enrichment
_GROWTH_FEATURES = (
    _STARTER_FEATURES + ","
    "deals,accounts,booking_links,tickets,crm_dashboard,"
    "campaigns,workflows,reports,social,ai_chat,"
    "segments,tags,crm_templates,api_vault"
)
# Pro: voice/call center + advanced AI (tools, images) + power builder features
_PRO_FEATURES = (
    _GROWTH_FEATURES + ","
    "voice_lab,ai_tools,ai_images,catalog,cts,link_shortener,comms_analytics"
)

_DEFAULT_PLANS = [
    {
        "name": "Free Trial",
        "price": 0.0,
        "currency": "INR",
        "billing_interval": "month",
        "default_user_limit": 5,
        "trial_days": 14,
        "description": "14-day free trial with access to all features",
        "features": "all",
        "is_active": True,
    },
    {
        "name": "Starter",
        "price": 2900.0,
        "currency": "INR",
        "billing_interval": "month",
        "default_user_limit": 10,
        "trial_days": 0,
        "description": "Core tools for small teams",
        "features": _STARTER_FEATURES,
        "is_active": True,
    },
    {
        "name": "Growth",
        "price": 7900.0,
        "currency": "INR",
        "billing_interval": "month",
        "default_user_limit": 25,
        "trial_days": 0,
        "description": "Pipeline, automation, analytics and outreach for growing teams",
        "features": _GROWTH_FEATURES,
        "is_active": True,
    },
    {
        "name": "Pro",
        "price": 14900.0,
        "currency": "INR",
        "billing_interval": "month",
        "default_user_limit": 50,
        "trial_days": 0,
        "description": "Full platform — voice, advanced AI and power builder features",
        "features": _PRO_FEATURES,
        "is_active": True,
    },
    {
        "name": "Enterprise",
        "price": 0.0,
        "currency": "INR",
        "billing_interval": "month",
        "default_user_limit": 9999,
        "trial_days": 0,
        "description": "Custom enterprise solution with unlimited users",
        "features": "all",
        "is_active": True,
    },
]


def seed_subscription_plans(db) -> None:
    """Upsert default subscription plans — creates new ones and updates features/descriptions on existing ones."""
    for plan_data in _DEFAULT_PLANS:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.name == plan_data["name"]).first()
        if plan:
            plan.features = plan_data["features"]
            plan.description = plan_data["description"]
            plan.default_user_limit = plan_data["default_user_limit"]
        else:
            db.add(SubscriptionPlan(**plan_data))
    db.commit()


def create_initial_data():
    db = SessionLocal()
    try:
        # Seed subscription plans
        seed_subscription_plans(db)

        # Create global permissions and Super Admin role
        role_service.create_global_permissions_and_super_admin(db)

        # Check if a default company exists, if not, create one
        default_company = company_service.get_companies(db, limit=1)
        if not default_company:
            company = company_service.create_company(db, schemas_company.CompanyCreate(name="HeyGenAlly"))
        else:
            company = default_company[0]

        # Create roles for the company
        role_service.create_initial_roles_for_company(db, company.id)

        # Get the Super Admin role
        super_admin_role = role_service.get_role_by_name(db, "Super Admin")

        # Check if a default user exists, if not, create one
        default_user = user_service.get_user_by_email(db, "admin@heygenally.com")
        if not default_user:
            user_service.create_user(db, schemas_user.UserCreate(email="admin@heygenally.com", password="password"), company_id=company.id, role_id=super_admin_role.id, is_super_admin=True)
        else:
            # If user exists but has no role, assign super admin role
            user = default_user
            if not user.role_id:
                user.role_id = super_admin_role.id
            if not user.is_super_admin:
                user.is_super_admin = True
            db.commit()

        # Check if a default agent exists, if not, create one
        default_agent_list = agent_service.get_agents(db, company.id, limit=1)
        if not default_agent_list:
            prompt = (
                "You are a helpful assistant. You have access to a set of tools. "
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
                create_api_call_tool(db, company.id)
        else:
            agent = default_agent_list[0]

        # Check if default widget settings exist, if not, create them
        default_widget_settings = widget_settings_service.get_widget_settings(db, agent_id=agent.id)
        if not default_widget_settings:
            widget_settings_service.create_widget_settings(db, schemas_widget_settings.WidgetSettingsCreate(agent_id=agent.id))

    finally:
        db.close()
