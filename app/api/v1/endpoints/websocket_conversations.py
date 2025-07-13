from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
import httpx
import os
import json

from app.schemas import chat_message as schemas_chat_message
from app.services import (
    chat_service,
    credential_service,
    agent_service,
    knowledge_base_service,
    tool_service,
    memory_service,
    workflow_service
)
from app.services.workflow_execution_service import WorkflowExecutionService
from app.models.workflow import Workflow
from app.core.dependencies import get_db
from app.core.config import settings

router = APIRouter()

@router.websocket("/ws/{company_id}/{agent_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: int, agent_id: int, session_id: str, db: Session = Depends(get_db)):
    
    await websocket.accept()
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        await websocket.send_text("Agent not found")
        await websocket.close()
        return

    # --- Agent System Prompt Construction ---
    system_prompt = agent.prompt or "You are a helpful AI assistant."

    if agent.personality:
        system_prompt += f"\n\nYour personality: {agent.personality}"
    if agent.response_style:
        system_prompt += f"\n\nYour response style: {agent.response_style}"
    if agent.instructions:
        system_prompt += f"\n\nInstructions: {agent.instructions}"

    # Load existing memories for context
    memories = memory_service.get_all_memories(db, agent_id, session_id)
    if memories:
        memory_context = "\n\nHere are some facts you remember from previous interactions:\n"
        for mem in memories:
            memory_context += f"- {mem.key}: {mem.value}\n"
        system_prompt += memory_context

    # --- Tool Specification for LLM ---
    agent_tools_spec = []
    # Add agent's pre-defined tools
    if agent.tools:
        for tool in agent.tools:
            agent_tools_spec.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            })

    # Add the special 'trigger_workflow' tool
    # This tool allows the LLM to dynamically trigger workflows with extracted parameters.
    trigger_workflow_tool = tool_service.get_tool_by_name(db, "trigger_workflow", company_id)
    if trigger_workflow_tool:
        agent_tools_spec.append({
            "type": "function",
            "function": {
                "name": trigger_workflow_tool.name,
                "description": trigger_workflow_tool.description,
                "parameters": trigger_workflow_tool.parameters
            }
        })

    # Add tool instructions to the system prompt if tools are available
    if agent_tools_spec:
        system_prompt += """
You have access to the following tools:
"""
        for tool_spec in agent_tools_spec:
            system_prompt += f"- {tool_spec['function']['name']}: {tool_spec['function']['description']}\n"
            if tool_spec['function']['parameters'] and tool_spec['function']['parameters'].get('properties'):
                system_prompt += "  Parameters:\n"
                for param_name, param_details in tool_spec['function']['parameters']['properties'].items():
                    param_type = param_details.get('type', 'any')
                    param_description = param_details.get('description', '')
                    system_prompt += f"    - {param_name} ({param_type}): {param_description}\n"
                if tool_spec['function']['parameters'].get('required'):
                    required_params = ', '.join(tool_spec['function']['parameters']['required'])
                    system_prompt += f"  Required Parameters: {required_params}\n"
        
        system_prompt += """
When appropriate, you can use these tools by calling them with the following format: `tool_name(arg1=value1, arg2=value2)`

Carefully consider the user's request and the descriptions of the available tools. If a tool's description matches the user's intent, use that tool. Extract all necessary parameters from the user's query. If you cannot extract all required parameters, ask the user for clarification.
"""

    # Send welcome message
    await websocket.send_json({"message": agent.welcome_message or f"Hello! You are connected to agent {agent.name}.", "sender": "agent"})
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # Save user message to chat history
            chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=data, sender="user"), agent_id, session_id, company_id, sender="user")

            response_message = "I'm sorry, I don't understand."
            try:
                api_key = None
                if agent.credential_id:
                    credential = credential_service.get_credential(db, agent.credential_id, company_id)
                    if credential:
                        api_key = credential.api_key
                    else:
                        response_message = "Error: Credential not found for this agent."
                
                if not api_key:
                    response_message = "Error: API key not configured for this agent."
                else:
                    # Fetch chat history for context
                    chat_history = chat_service.get_chat_messages(db, agent_id, session_id, company_id)
                    messages = []

                    # Add agent's prompt as a system message
                    messages.append({"role": "system", "content": system_prompt})

                    # Add knowledge base context if available and relevant to the current message
                    if agent.knowledge_base_id:
                        relevant_chunks = knowledge_base_service.find_relevant_chunks(db, agent.knowledge_base_id, company_id, data)
                        if relevant_chunks:
                            knowledge_base_context = "\n\nRelevant information from knowledge base:\n\n" + "\n\n".join(relevant_chunks)
                            messages.append({"role": "system", "content": knowledge_base_context})
                    
                    # Add past messages from chat history
                    for msg in chat_history:
                        # Filter out internal /tool-use messages and previous error messages from frontend
                        if not msg.message.startswith("/tool-use") and \
                           "An unexpected error occurred during groq processing" not in msg.message and \
                           "only integer scalar arrays can be converted to a scalar index" not in msg.message:
                            messages.append({"role": "user" if msg.sender == "user" else "assistant", "content": msg.message})

                    # Add current user message
                    messages.append({"role": "user", "content": data})

                    # --- First call to Groq (potentially with tools) ---
                    tool_call_response = None
                    if agent_tools_spec:
                        tool_call_response = await httpx.AsyncClient().post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "llama3-8b-8192",
                                "messages": messages,
                                "tools": agent_tools_spec,
                                "tool_choice": "auto",
                                "temperature": 0.7,
                                "max_tokens": 150,
                            },
                            timeout=30.0
                        )
                        tool_call_response.raise_for_status()
                        tool_call_data = tool_call_response.json()
                        
                        # --- Handle Tool Calls from Groq ---
                        if tool_call_data["choices"][0]["message"].get("tool_calls"):
                            tool_calls = tool_call_data["choices"][0]["message"]["tool_calls"]
                            messages.append(tool_call_data["choices"][0]["message"])
                            
                            for tool_call in tool_calls:
                                function_name = tool_call["function"]["name"]
                                function_args = tool_call["function"]["arguments"]
                                
                                tool_output = None
                                if function_name == "trigger_workflow":
                                    # --- Special handling for trigger_workflow tool ---
                                    try:
                                        args_dict = json.loads(function_args)
                                        workflow_name = args_dict.get("workflow_name")
                                        workflow_inputs = args_dict.get("inputs", {})

                                        workflow_to_execute = workflow_service.get_workflow_by_name(db, workflow_name, agent_id)
                                        if workflow_to_execute:
                                            workflow_executor = WorkflowExecutionService(db)
                                            workflow_results = workflow_executor.execute_workflow(workflow_to_execute, initial_context=workflow_inputs)
                                            
                                            # Extract the final response from workflow results
                                            if "final_response" in workflow_results and "output" in workflow_results["final_response"]:
                                                tool_output = workflow_results["final_response"]["output"]
                                            else:
                                                tool_output = f"Workflow '{workflow_name}' executed. No final response found."
                                        else:
                                            tool_output = f"Error: Workflow '{workflow_name}' not found."
                                    except Exception as e:
                                        tool_output = f"Error triggering workflow: {e}"
                                else:
                                    # --- General tool execution ---
                                    tool_code = None
                                    local_scope = {}
                                    
                                    for t in agent.tools:
                                        if t.name == function_name:
                                            tool_code = t.code
                                            break
                                    
                                    if tool_code:
                                        try:
                                            exec_globals = {"args": json.loads(function_args), "result": None}
                                            exec(tool_code, exec_globals, local_scope)
                                            
                                            # Get the 'run' function from the local scope
                                            tool_function = local_scope.get("run")
                                                                                
                                            if not callable(tool_function):
                                                return {"error": "Tool code does not define a callable 'run' function"}
                            
                                            tool_output = tool_function(args=json.loads(function_args))                
                                        except Exception as e:
                                            tool_output = f"Error executing tool {function_name}: {e}"
                                    else:
                                        tool_output = f"Tool {function_name} not found."

                                # Append tool output to messages for the second Groq call
                                messages.append({
                                    "tool_call_id": tool_call["id"],
                                    "role": "tool",
                                    "name": function_name,
                                    "content": str(tool_output),
                                })
                                # Optionally, send tool execution status to frontend
                                chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=f"Tool {function_name} executed. Output: {tool_output}", sender="tool"), agent_id, session_id, company_id, sender="tool")
                                await websocket.send_json({"message": f"Tool {function_name} executed. Output: {tool_output}", "sender": "tool"})
                            
                            # --- Second call to Groq with tool output ---
                            final_response = await httpx.AsyncClient().post(
                                "https://api.groq.com/openai/v1/chat/completions",
                                headers={
                                    "Authorization": f"Bearer {api_key}",
                                    "Content-Type": "application/json",
                                },
                                json={
                                    "model": "llama3-8b-8192",
                                    "messages": messages,
                                    "temperature": 0.7,
                                    "max_tokens": 150,
                                },
                                timeout=30.0
                            )
                            final_response.raise_for_status()
                            grok_response = final_response.json()
                            response_message = grok_response["choices"][0]["message"]["content"]
                            if tool_calls: # If tool was called, clear the response message to avoid double response
                                response_message = ""
                        else:
                            # Groq returned a direct message, no tool call
                            response_message = tool_call_data["choices"][0]["message"]["content"]
                    else:
                        # --- Original Groq call if no tools are available or specified ---
                        response = await httpx.AsyncClient().post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": "llama3-8b-8192",
                                "messages": messages,
                                "temperature": 0.7,
                                "max_tokens": 150,
                            },
                            timeout=30.0
                        )
                        response.raise_for_status()
                        grok_response = response.json()
                        response_message = grok_response["choices"][0]["message"]["content"]

            except httpx.RequestError as e:
                response_message = f"Error communicating with Groq API: {e}"
            except httpx.HTTPStatusError as e:
                response_message = f"Groq API returned an error: {e.response.status_code} - {e.response.text}"
            except Exception as e:
                response_message = f"An unexpected error occurred during Groq processing: {e}"

            # Send final response to frontend and save to chat history
            if response_message:
                chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=response_message, sender="agent"), agent_id, session_id, company_id, sender="agent")
                await websocket.send_json({"message": response_message, "sender": "agent"})

            # Example: Save a memory (in a real scenario, this would be more sophisticated)
            if "remember" in data.lower():
                memory_service.create_memory(db, schemas_memory.MemoryCreate(key="last_user_request", value=data), agent_id, session_id)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Catch any unexpected errors during the WebSocket connection
        print(f"WebSocket error: {e}")
        await websocket.send_text(f"An unexpected error occurred: {e}")
    finally:
        # Ensure the database session is closed
        db.close()