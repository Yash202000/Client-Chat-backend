import asyncio
from sqlalchemy.orm import Session
from fastmcp.client import Client

from app.core.database import SessionLocal
from app.services import tool_service, agent_service
from app.schemas.tool import ToolCreate, ToolSchema, FunctionSchema

# --- Configuration ---
MCP_SERVER_URL = "http://127.0.0.1:8100"
AGENT_NAME = "Default Agent"
COMPANY_ID = 1

def adapt_mcp_schema_to_tool_schema(mcp_tool) -> ToolSchema:
    """Converts the schema from the fastmcp client to the application's ToolSchema."""
    
    # The fastmcp client gives us a schema that's close but needs adapting.
    # The main difference is that the parameters are nested inside a 'properties' dict.
    mcp_schema = mcp_tool.inputSchema
    
    # Extract the actual parameter definitions
    params_ref = mcp_schema.get('properties', {}).get('params', {}).get('$ref', '')
    if not params_ref:
        parameters_schema = {"type": "object", "properties": {}}
    else:
        param_model_name = params_ref.split('/')[-1]
        parameters_schema = mcp_schema.get('$defs', {}).get(param_model_name, {"type": "object", "properties": {}})

    return ToolSchema(
        function=FunctionSchema(
            name=mcp_tool.name,
            description=mcp_tool.description,
            parameters=parameters_schema
        )
    )

async def main():
    db: Session = SessionLocal()
    try:
        # 1. Get the agent
        agent = agent_service.get_agent_by_name(db, AGENT_NAME, COMPANY_ID)
        if not agent:
            print(f"Error: Agent '{AGENT_NAME}' not found for company {COMPANY_ID}.")
            return
        print(f"Found agent: {agent.name}")

        # 2. Inspect the MCP server to get its tools
        print(f"Connecting to MCP server at {MCP_SERVER_URL} to get tools...")
        async with Client(MCP_SERVER_URL) as client:
            mcp_tools = await client.list_tools()
        print(f"Found {len(mcp_tools)} tools on MCP server.")

        # 3. Create or update these tools in the main application DB
        db_tools = []
        for mcp_tool in mcp_tools:
            tool_name = mcp_tool.name
            print(f"  - Processing tool: {tool_name}")
            
            # Adapt the schema
            adapted_schema = adapt_mcp_schema_to_tool_schema(mcp_tool)

            # Check if tool already exists
            db_tool = tool_service.get_tool_by_name(db, tool_name, COMPANY_ID)
            
            description = mcp_tool.description or f"No description available for {tool_name}."
            print(f"    - Tool Name: {tool_name}, Description: '{description}'")

            tool_data = ToolCreate(
                name=tool_name,
                description=description,
                schema_=adapted_schema.dict(),
                tool_type="mcp",
                company_id=COMPANY_ID
            )

            if db_tool:
                print(f"    - Tool '{tool_name}' already exists. Updating...")
                db_tool = tool_service.update_tool(db, db_tool.id, tool_data)
            else:
                print(f"    - Tool '{tool_name}' does not exist. Creating...")
                db_tool = tool_service.create_tool(db, tool_data, COMPANY_ID)
            
            db_tools.append(db_tool)

        # 4. Associate all fetched tools with the agent
        print(f"\nAssociating {len(db_tools)} tools with agent '{agent.name}'...")
        updated_agent = agent_service.associate_tools_with_agent(db, agent.id, [t.id for t in db_tools])
        
        print("\n--- Synchronization Complete ---")
        print(f"Agent '{updated_agent.name}' is now associated with the following tools:")
        for tool in updated_agent.tools:
            print(f"  - {tool.name}")
        print("\nRun your query against the agent again.")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
