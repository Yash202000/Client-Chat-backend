
import asyncio
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.services import role_service, permission_service
from app.schemas import role as schemas_role
from app.schemas import permission as schemas_permission

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
    # Internal Chat
    "chat:create": "Create internal chat channels",
    "chat:read": "Read and participate in internal chat",
    "chat:update": "Update chat channels",
    "chat:delete": "Delete chat channels",
    # AI Image Generation
    "image:create": "Generate AI images",
    "image:read": "View AI image gallery",
    "image:update": "Update AI images",
    "image:delete": "Delete AI images",
}

# Define all roles and their associated permissions
ROLES = {
    "Super Admin": {
        "description": "Has all permissions",
        "permissions": list(PERMISSIONS.keys()),
    },
    "Admin": {
        "description": "Full access to all features within their company",
        "permissions": [
            "user:create", "user:read", "user:update", "user:delete",
            "role:create", "role:read", "role:update", "role:delete",
            "agent:create", "agent:read", "agent:update", "agent:delete",
            "workflow:create", "workflow:read", "workflow:update", "workflow:delete",
            "analytics:read",
            "company_settings:update",
        ],
    },
    "Agent Builder": {
        "description": "Can create and manage agents and workflows",
        "permissions": [
            "agent:create", "agent:read", "agent:update", "agent:delete",
            "workflow:create", "workflow:read", "workflow:update", "workflow:delete",
            "tool:read", "knowledgebase:read", "analytics:read",
            "ai-tool:read", "ai-tool-category:read",
            "conversation:read", "conversation:update",
            "voice:create", "voice:read", "voice:update", "voice:delete",
            "chat:read", "chat:create",
            "image:create", "image:read",
        ],
    },
    "Analyst": {
        "description": "Read-only access to dashboards and analytics",
        "permissions": [
            "agent:read", "workflow:read", "analytics:read",
            "conversation:read",
        ],
    },
    "Client": {
        "description": "Read-only access for clients",
        "permissions": ["client:read_dashboard"],
    },
}

async def create_default_roles_and_permissions():
    db: Session = SessionLocal()
    try:
        # Create permissions
        for name, description in PERMISSIONS.items():
            permission = permission_service.get_permission_by_name(db, name=name)
            if not permission:
                permission_in = schemas_permission.PermissionCreate(name=name, description=description)
                permission_service.create_permission(db, permission=permission_in)

        # Create roles and assign permissions
        for name, role_data in ROLES.items():
            role = role_service.get_role_by_name(db, name=name)
            if not role:
                role_in = schemas_role.RoleCreate(name=name, description=role_data["description"])
                # Super Admin is not company specific
                company_id = None if name == "Super Admin" else 1 # Default to company 1 for others
                db_role = role_service.create_role(db, role=role_in, company_id=company_id)
                
                permission_ids = []
                for perm_name in role_data["permissions"]:
                    permission = permission_service.get_permission_by_name(db, name=perm_name)
                    if permission:
                        permission_ids.append(permission.id)
                
                role_service.assign_permissions_to_role(db, role_id=db_role.id, permission_ids=permission_ids)

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(create_default_roles_and_permissions())
    print("Default roles and permissions created successfully.")
