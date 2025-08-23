import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from typing import Dict, Any
from fastmcp.client import Client
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, get_current_user
from app.models.user import User
from app.services import credential_service
from app.services.vault_service import vault_service

router = APIRouter()

class McpInspectRequest(BaseModel):
    url: HttpUrl

class McpExecuteRequest(BaseModel):
    url: HttpUrl
    tool_name: str
    parameters: Dict[str, Any]


def get_access_token_if_available(db: Session, company_id: int):
    """Return Google access token string if available, else None."""
    google_credential = credential_service.get_credential_by_service_name(
        db, service_name="google", company_id=company_id
    )
    if google_credential:
        try:
            decrypted_creds = vault_service.decrypt(google_credential.encrypted_credentials)
            access_token = json.loads(decrypted_creds).get("token")
            if access_token:
                return access_token
        except Exception as e:
            print(f"Could not decrypt credentials, proceeding without them. Error: {e}")
    return None


@router.post("/inspect")
async def inspect_mcp_server(
    request: McpInspectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    token = get_access_token_if_available(db, current_user.company_id)

    try:
        async with Client(str(request.url), auth=f"Bearer {token}") as client:
            tool_list = await client.list_tools()

        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema,
            }
            for tool in tool_list
        ]
        return {"tools": tools}

    except Exception as e:
        if token is None:
            return {
                "authentication_required": True,
                "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
                "message": "This tool requires Google authentication. Please connect your Google account to proceed.",
            }
        raise HTTPException(
            status_code=400,
            detail=f"Failed to connect or inspect MCP server. Error: {str(e)}",
        )


@router.post("/execute")
async def execute_mcp_tool(
    request: McpExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    token = get_access_token_if_available(db, current_user.company_id)

    try:
        async with Client(str(request.url), token=token) as client:
            result = await client.call_tool(request.tool_name, request.parameters)
            return {"result": result}
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to execute tool on MCP server. Error: {str(e)}",
        )
