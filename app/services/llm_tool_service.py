
from app.llm_providers.gemini_provider import generate_response as ggr
from app.llm_providers.groq_provider import generate_response as grg
from app.services import knowledge_base_service, tool_service
from sqlalchemy.orm import Session
from app.models.tool import Tool
from fastmcp.client import Client
import asyncio

class LLMToolService:
    def __init__(self, db: Session):
        self.db = db

    async def execute(self, model: str, system_prompt: str, chat_history: list, user_prompt: str, company_id: int, tools: list[Tool], knowledge_base_id: int = None):
        print(f"DEBUG: LLMToolService.execute called with tools: {tools}")
        augmented_prompt = user_prompt

        if knowledge_base_id:
            relevant_chunks = knowledge_base_service.find_relevant_chunks(
                self.db, knowledge_base_id, company_id, user_prompt
            )
            if relevant_chunks:
                context = "\n\nContext:\n" + "\n".join(relevant_chunks)
                augmented_prompt = f"{user_prompt}{context}"
                print(f"DEBUG: Augmented prompt with KB context: {augmented_prompt}")
            else:
                print("DEBUG: No relevant chunks found for the prompt.")

        full_chat_history = chat_history + [{"role": "user", "content": augmented_prompt}]

        # Format the tools for the LLM provider
        formatted_tools = []
        for tool in tools:
            if tool.tool_type == 'custom':
                formatted_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name.replace(" ", "_"),
                        "description": tool.description,
                        "parameters": tool.parameters or {},
                    },
                })
            elif tool.tool_type == 'mcp' and tool.mcp_server_url:
                # This is an MCP connection, dynamically fetch all its tools
                try:
                    async with Client(str(tool.mcp_server_url)) as client:
                        all_mcp_tools_metadata = await client.list_tools()
                    
                    for mcp_tool_metadata in all_mcp_tools_metadata:
                        # Namespace the tool name to avoid collisions if multiple MCP connections
                        namespaced_tool_name = f"{tool.name.replace(' ', '_')}___{mcp_tool_metadata.name.replace(' ', '_')}"
                        
                        # Extract the actual parameter schema from the inputSchema
                        tool_parameters = {
                            "type": "object",
                            **mcp_tool_metadata.inputSchema.get('$defs', {}).get(
                                mcp_tool_metadata.inputSchema.get('properties', {}).get('params', {}).get('$ref', '').split('/')[-1],
                                {}
                            )
                        }
                        print(f"DEBUG: Dynamically fetched parameters for MCP tool {namespaced_tool_name}: {tool_parameters}")
                        
                        formatted_tools.append({
                            "type": "function",
                            "function": {
                                "name": namespaced_tool_name,
                                "description": mcp_tool_metadata.description,
                                "parameters": tool_parameters,
                            },
                        })
                except Exception as e:
                    print(f"ERROR: Failed to fetch tools from MCP server {tool.mcp_server_url}. Error: {e}")

        print(f"DEBUG: Formatted tools sent to LLM: {formatted_tools}")

        provider, model_name = model.split('/')
        
        if provider == "gemini":
            response = ggr(db=self.db, company_id=company_id, model_name=model_name, system_prompt=system_prompt, chat_history=full_chat_history, tools=formatted_tools)
            return response
        elif provider == "groq":
            response = grg(db=self.db, company_id=company_id, model_name=model_name, system_prompt=system_prompt, chat_history=full_chat_history, tools=formatted_tools)
            return response
        else:
            return {"error": f"Unsupported LLM provider: {provider}"}
