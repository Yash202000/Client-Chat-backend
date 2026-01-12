
from sqlalchemy.orm import Session, joinedload
from app.models import role as models_role, permission as models_permission
from app.schemas import role as schemas_role

# Define all permissions
PERMISSIONS = {
    # User Management
    "user:create": "Create a new user",
    "user:read": "Read user information",
    "user:update": "Update user information",
    "user:delete": "Delete a user",
    # Role Management
    "role:create": "Create a new role",
    "role:read": "Read role information",
    "role:update": "Update role information",
    "role:delete": "Delete a role",
    # Agent Management
    "agent:create": "Create a new agent",
    "agent:read": "Read agent information",
    "agent:update": "Update agent information",
    "agent:delete": "Delete an agent",
    # Workflow Management
    "workflow:create": "Create a new workflow",
    "workflow:read": "Read workflow information",
    "workflow:update": "Update workflow information",
    "workflow:delete": "Delete a workflow",
    # Tool Management
    "tool:create": "Create tools",
    "tool:read": "Read tools",
    "tool:update": "Update tools",
    "tool:delete": "Delete tools",
    # KnowledgeBase Management
    "knowledgebase:create": "Create knowledge bases",
    "knowledgebase:read": "Read knowledge bases",
    "knowledgebase:update": "Update knowledge bases",
    "knowledgebase:delete": "Delete knowledge bases",
    # Analytics
    "analytics:read": "Read analytics data",
    # Company Settings
    "company_settings:update": "Update company settings",
    "billing:manage": "Manage billing and subscription",
    # Client Access
    "client:read_dashboard": "Read-only access to the client dashboard",
    # AI Tool Management
    "ai-tool:create": "Create AI tools",
    "ai-tool:read": "Read AI tools",
    "ai-tool:update": "Update AI tools",
    "ai-tool:delete": "Delete AI tools",
    "ai-tool:import": "Import AI tools from a file",
    "ai-tool:export": "Export AI tools to a file",
    "ai-tool-category:create": "Create AI tool categories",
    "ai-tool-category:read": "Read AI tool categories",
    "ai-tool-category:update": "Update AI tool categories",
    "ai-tool-category:delete": "Delete AI tool categories",
    # Conversation Management
    "conversation:create": "Create conversations",
    "conversation:read": "Read conversations and active clients",
    "conversation:update": "Update conversations",
    "conversation:delete": "Delete conversations",
    # Voice Lab
    "voice:create": "Create and manage voice models",
    "voice:read": "Read voice models",
    "voice:update": "Update voice models",
    "voice:delete": "Delete voice models",
    # Internal Chat (Team Chat)
    "chat:create": "Create internal chat channels",
    "chat:read": "Read and participate in internal team chat",
    "chat:update": "Update chat channels",
    "chat:delete": "Delete chat channels",
    # AI Chat
    "ai-chat:read": "Access AI chat assistant",
    # AI Image Generation
    "image:create": "Generate AI images",
    "image:read": "View AI image gallery",
    "image:update": "Update AI images",
    "image:delete": "Delete AI images",
    # CRM - Leads
    "lead:create": "Create leads",
    "lead:read": "Read leads",
    "lead:update": "Update leads",
    "lead:delete": "Delete leads",
    # CRM - Contacts
    "contact:create": "Create contacts",
    "contact:read": "Read contacts",
    "contact:update": "Update contacts",
    "contact:delete": "Delete contacts",
    # CRM - Campaigns
    "campaign:create": "Create campaigns",
    "campaign:read": "Read campaigns",
    "campaign:update": "Update campaigns",
    "campaign:delete": "Delete campaigns",
    # CRM - Tags
    "tag:create": "Create tags",
    "tag:read": "Read tags",
    "tag:update": "Update tags",
    "tag:delete": "Delete tags",
    # CRM - Segments
    "segment:create": "Create segments",
    "segment:read": "Read segments",
    "segment:update": "Update segments",
    "segment:delete": "Delete segments",
    # CRM - Email Templates
    "email_template:create": "Create email templates",
    "email_template:read": "Read email templates",
    "email_template:update": "Update email templates",
    "email_template:delete": "Delete email templates",
    # Message Templates
    "message_template:create": "Create message templates",
    "message_template:read": "Read message templates",
    "message_template:update": "Update message templates",
    "message_template:delete": "Delete message templates",
    # Companies Management (Super Admin)
    "company:create": "Create companies",
    "company:read": "Read companies",
    "company:update": "Update companies",
    "company:delete": "Delete companies",
}

# Page-based permissions for controlling access to dashboard sections
# Each sidebar item has its own permission for granular control
PAGE_PERMISSIONS = {
    # Core Operations
    "page:conversations": "Access to active clients and conversations",
    "page:agents": "Access to agents list",
    "page:agent_builder": "Access to agent builder",
    "page:widget_designer": "Access to widget designer",
    # Analytics
    "page:reports": "Access to analytics and reports",
    # CRM - Individual permissions for each section
    "page:crm_dashboard": "Access to CRM dashboard",
    "page:contacts": "Access to contacts management",
    "page:leads": "Access to leads management",
    "page:campaigns": "Access to campaigns",
    "page:tags": "Access to tags management",
    "page:segments": "Access to segments",
    "page:crm_templates": "Access to CRM email templates",
    # Configuration & Resources
    "page:knowledge_base": "Access to knowledge base",
    "page:tools": "Access to custom tools",
    "page:workflows": "Access to workflow builder",
    "page:voice_lab": "Access to voice lab",
    # Team & Communication
    "page:team_management": "Access to team management",
    "page:team_chat": "Access to team chat",
    "page:message_templates": "Access to message templates",
    # AI Features - Individual permissions
    "page:ai_chat": "Access to AI chat",
    "page:ai_tools": "Access to AI tools",
    "page:ai_image_generator": "Access to AI image generator",
    "page:ai_image_gallery": "Access to AI image gallery",
    "page:vision_ai": "Access to Vision AI / object detection",
    # System & Administration
    "page:settings": "Access to company settings",
    "page:api_vault": "Access to API vault",
    "page:billing": "Access to billing management",
}

def get_role(db: Session, role_id: int, company_id: int = None):
    query = db.query(models_role.Role).filter(models_role.Role.id == role_id)
    if company_id:
        query = query.filter(models_role.Role.company_id == company_id)
    return query.first()

def get_role_by_name(db: Session, name: str, company_id: int = None):
    query = db.query(models_role.Role).filter(models_role.Role.name == name)
    if company_id:
        query = query.filter(models_role.Role.company_id == company_id)
    else:
        query = query.filter(models_role.Role.company_id.is_(None))
    return query.first()

def get_roles(db: Session, company_id: int, skip: int = 0, limit: int = 100):
    return db.query(models_role.Role).options(joinedload(models_role.Role.permissions)).filter(models_role.Role.company_id == company_id).offset(skip).limit(limit).all()

def create_role(db: Session, role: schemas_role.RoleCreate, company_id: int = None):
    db_role = models_role.Role(
        name=role.name,
        description=role.description,
        company_id=company_id
    )
    
    if role.permission_ids:
        permissions = db.query(models_permission.Permission).filter(models_permission.Permission.id.in_(role.permission_ids)).all()
        db_role.permissions.extend(permissions)

    db.add(db_role)
    db.commit()
    db.refresh(db_role)
    return db_role

def update_role(db: Session, role_id: int, role: schemas_role.RoleUpdate, company_id: int):
    db_role = get_role(db, role_id, company_id)
    if db_role:
        db_role.name = role.name
        db_role.description = role.description
        
        if role.permission_ids is not None:
            db_role.permissions.clear()
            permissions = db.query(models_permission.Permission).filter(models_permission.Permission.id.in_(role.permission_ids)).all()
            db_role.permissions.extend(permissions)
            
        db.commit()
        db.refresh(db_role)
    return db_role

def delete_role(db: Session, role_id: int, company_id: int):
    db_role = get_role(db, role_id, company_id)
    if db_role:
        db.delete(db_role)
        db.commit()
    return db_role

def assign_permissions_to_role(db: Session, role_id: int, permission_ids: list[int]):
    role = db.query(models_role.Role).filter(models_role.Role.id == role_id).first()
    if role:
        role.permissions.clear()
        permissions = db.query(models_permission.Permission).filter(models_permission.Permission.id.in_(permission_ids)).all()
        role.permissions.extend(permissions)
        db.commit()
        db.refresh(role)
    return role

def create_global_permissions_and_super_admin(db: Session):
    """
    Creates all permissions and the Super Admin role.
    This should be run once on application startup.
    Also updates Super Admin with any new permissions.
    """
    # Old page permissions to remove (replaced by granular permissions)
    old_page_permissions = [
        "page:crm", "page:analytics", "page:ai_features", "page:team",
        "page:knowledge", "page:integrations",
    ]

    # Remove old page permissions that are no longer used
    for old_perm_name in old_page_permissions:
        old_perm = db.query(models_permission.Permission).filter_by(name=old_perm_name).first()
        if old_perm:
            # Remove from all roles first
            old_perm.roles.clear()
            db.delete(old_perm)
            print(f"[Startup] Removed old permission: {old_perm_name}")
    db.commit()

    # Create permissions if they don't exist (both API and page permissions)
    all_permissions = {**PERMISSIONS, **PAGE_PERMISSIONS}
    new_permissions_added = False
    for name, desc in all_permissions.items():
        db_perm = db.query(models_permission.Permission).filter_by(name=name).first()
        if not db_perm:
            db_perm = models_permission.Permission(name=name, description=desc)
            db.add(db_perm)
            new_permissions_added = True
            print(f"[Startup] Added new permission: {name}")
    db.commit()

    # Create or update Super Admin role
    super_admin_role = get_role_by_name(db, "Super Admin")
    if not super_admin_role:
        super_admin_role = create_role(db, schemas_role.RoleCreate(name="Super Admin", description="Has all permissions"), company_id=None)

    # Always assign all permissions to Super Admin (in case new ones were added)
    all_permissions = db.query(models_permission.Permission).all()
    permission_ids = [p.id for p in all_permissions]
    assign_permissions_to_role(db, role_id=super_admin_role.id, permission_ids=permission_ids)

    if new_permissions_added:
        print(f"[Startup] Added new permissions and updated Super Admin role")

def create_initial_roles_for_company(db: Session, company_id: int):
    """
    Creates the initial roles for a new company.
    """
    # Admin gets all API permissions (except company management and client dashboard)
    # plus all page permissions
    admin_api_perms = [p for p in PERMISSIONS.keys() if p not in ["client:read_dashboard", "company:create", "company:read", "company:update", "company:delete"]]
    admin_page_perms = list(PAGE_PERMISSIONS.keys())

    roles_to_permissions = {
        "Admin": admin_api_perms + admin_page_perms,
        "Agent Builder": [
            # API permissions
            "agent:create", "agent:read", "agent:update", "agent:delete",
            "workflow:create", "workflow:read", "workflow:update", "workflow:delete",
            "tool:read", "knowledgebase:read", "analytics:read",
            "ai-tool:read", "ai-tool-category:read",
            "conversation:read", "conversation:update",
            "voice:create", "voice:read", "voice:update", "voice:delete",
            "chat:read", "chat:create",
            "ai-chat:read",
            "image:create", "image:read",
            # CRM permissions (limited)
            "lead:read", "lead:create", "lead:update",
            "contact:read", "contact:create", "contact:update",
            "campaign:read",
            "tag:read",
            "segment:read",
            "email_template:read",
            # Message Templates
            "message_template:read", "message_template:create",
            # Page permissions
            "page:conversations", "page:agents", "page:agent_builder",
            "page:workflows", "page:tools", "page:knowledge_base",
            "page:voice_lab", "page:team_management", "page:team_chat",
            "page:message_templates", "page:ai_chat", "page:ai_tools",
            "page:ai_image_generator", "page:ai_image_gallery",
            "page:contacts", "page:leads",
        ],
        "Analyst": [
            # API permissions
            "agent:read", "workflow:read", "analytics:read",
            "conversation:read",
            # CRM read-only permissions
            "lead:read",
            "contact:read",
            "campaign:read",
            "tag:read",
            "segment:read",
            "email_template:read",
            "message_template:read",
            # Page permissions
            "page:conversations", "page:reports",
            "page:crm_dashboard", "page:contacts", "page:leads",
            "page:campaigns", "page:tags", "page:segments", "page:crm_templates",
        ],
        "Client": [
            "client:read_dashboard", "agent:read"
            # No page permissions - uses client:read_dashboard for access
        ]
    }

    for name, perm_names in roles_to_permissions.items():
        db_role = get_role_by_name(db, name, company_id)
        if not db_role:
            db_role = create_role(db, schemas_role.RoleCreate(name=name, description=f"The {name} role"), company_id=company_id)

        # Always update permissions (in case new ones were added)
        permissions = db.query(models_permission.Permission).filter(models_permission.Permission.name.in_(perm_names)).all()
        permission_ids = [p.id for p in permissions]
        assign_permissions_to_role(db, role_id=db_role.id, permission_ids=permission_ids)

