from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
import httpx
import os
import json

from app.schemas import chat_message as schemas_chat_message
from app.services import chat_service, credential_service, agent_service, knowledge_base_service, tool_service, memory_service
from app.core.dependencies import get_db
from app.core.config import settings

router = APIRouter()

@router.websocket("/ws/{company_id}/{agent_id}/{session_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: int, agent_id: int, session_id: str, db: Session = Depends(get_db)):
    print(f"WebSocket connection attempt: company_id={company_id}, agent_id={agent_id}, session_id={session_id}")
    await websocket.accept()
    agent = agent_service.get_agent(db, agent_id, company_id)
    if not agent:
        await websocket.send_text("Agent not found")
        await websocket.close()
        return

    system_prompt = agent.prompt or "You are a helpful AI assistant."

    # Load existing memories
    memories = memory_service.get_all_memories(db, agent_id, session_id)
    if memories:
        memory_context = "\n\nHere are some facts you remember from previous interactions:\n"
        for mem in memories:
            memory_context += f"- {mem.key}: {mem.value}\n"
        system_prompt += memory_context

    # Add tool instructions to the system prompt
    agent_tools_spec = []
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

    if agent_tools_spec:
        system_prompt += "\n\nYou have access to the following tools:\n"
        for tool_spec in agent_tools_spec:
            system_prompt += f"- {tool_spec['function']['name']}: {tool_spec['function']['description']}\n"
        system_prompt += """
When appropriate, you can use these tools by calling them with the following format: `tool_name(arg1=value1, arg2=value2)`
When performing addition operations, consider using the `add_numbers` tool. For example, to add 5 and 3, you should respond with: `add_numbers(a=5, b=3)`
"""

    await websocket.send_json({"message": agent.welcome_message or f"Hello! You are connected to agent {agent.name}.", "sender": "agent"})
    
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received message from frontend: {data}")
            chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=data, sender="user"), agent_id, session_id, company_id, sender="user")

            # Grok integration
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
                    print(f"Using API Key: {api_key[:5]}...") # Log first 5 chars of API key
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
                           "An unexpected error occurred during Grok processing" not in msg.message and \
                           "only integer scalar arrays can be converted to a scalar index" not in msg.message:
                            messages.append({"role": "user" if msg.sender == "user" else "assistant", "content": msg.message})

                    # Add current user message
                    messages.append({"role": "user", "content": data})

                    print(f"Messages sent to Groq: {messages}")
                    
                    print(agent_tools_spec)
                    print(agent.tools)

                    # First call to Groq - potentially with tools
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
                        
                        print()
                        
                        
                        print(tool_call_data)
                        print(tool_call_data["choices"][0]["message"].get("tool_calls"))
                        
                        if tool_call_data["choices"][0]["message"].get("tool_calls"):
                            tool_calls = tool_call_data["choices"][0]["message"]["tool_calls"]
                            messages.append(tool_call_data["choices"][0]["message"])
                            
                            for tool_call in tool_calls:
                                print("calling tool here ")
                                function_name = tool_call["function"]["name"]
                                function_args = tool_call["function"]["arguments"]
                                
                                # Find the tool's code and execute it
                                tool_code = None
                                for t in agent.tools:
                                    if t.name == function_name:
                                        tool_code = t.code
                                        break
                                
                                if tool_code:
                                    try:
                                        print(f"Executing tool: {function_name} with args: {function_args}")
                                        # Execute the tool code dynamically
                                        # WARNING: Executing arbitrary code is dangerous. 
                                        # In a production environment, use a secure sandbox.
                                        exec_globals = {"args": json.loads(function_args), "result": None}
                                        exec(tool_code, exec_globals)
                                        tool_output = exec_globals["result"]
                                        print(f"Tool {function_name} executed. Output: {tool_output}")
                                        messages.append({
                                            "tool_call_id": tool_call["id"],
                                            "role": "tool",
                                            "name": function_name,
                                            "content": str(tool_output),
                                        })
                                        chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=f"Tool {function_name} executed. Output: {tool_output}", sender="tool"), agent_id, session_id, company_id, sender="tool")
                                        await websocket.send_json({"message": f"Tool {function_name} executed. Output: {tool_output}", "sender": "tool"})
                                    except Exception as e:
                                        error_message = f"Error executing tool {function_name}: {e}"
                                        messages.append({
                                            "tool_call_id": tool_call["id"],
                                            "role": "tool",
                                            "name": function_name,
                                            "content": error_message,
                                        })
                                        print(f"Tool execution error: {error_message}")
                                else:
                                    messages.append({
                                        "tool_call_id": tool_call["id"],
                                        "role": "tool",
                                        "name": function_name,
                                        "content": f"Tool {function_name} not found.",
                                    })
                            
                            # Second call to Groq with tool output
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
                            if tool_calls: # If tool was called, clear the response message
                                response_message = ""
                        else:
                            response_message = tool_call_data["choices"][0]["message"]["content"]
                    else:
                        # Original Groq call if no tools are available
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
                response_message = f"Error communicating with Grok API: {e}"
                print(response_message)
            except httpx.HTTPStatusError as e:
                response_message = f"Grok API returned an error: {e.response.status_code} - {e.response.text}"
                print(response_message)
            except Exception as e:
                response_message = f"An unexpected error occurred during Grok processing: {e}"
                print(response_message)

            if response_message:
                chat_service.create_chat_message(db, schemas_chat_message.ChatMessageCreate(message=response_message, sender="agent"), agent_id, session_id, company_id, sender="agent")
                await websocket.send_json({"message": response_message, "sender": "agent"})

            # Example: Save a memory (in a real scenario, this would be more sophisticated)
            if "remember" in data.lower():
                memory_service.create_memory(db, schemas_memory.MemoryCreate(key="last_user_request", value=data), agent_id, session_id)

    except WebSocketDisconnect:
        print("WebSocket disconnected")
    except Exception as e:
        print(f"WebSocket Error: {e}")