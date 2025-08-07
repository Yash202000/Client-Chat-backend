import json
import re
import uuid
from sqlalchemy.orm import Session
from app.models import workflow
from app.models.workflow import Workflow
from app.models.tool import Tool
from app.services import tool_service, conversation_session_service, knowledge_base_service, workflow_service
from app.schemas.conversation_session import ConversationSessionUpdate
from app.services.graph_execution_engine import GraphExecutionEngine
from app.services.llm_tool_service import LLMToolService

import requests
import numexpr

class WorkflowExecutionService:
    def __init__(self, db: Session):
        self.db = db
        self.llm_tool_service = LLMToolService(db)

    def _execute_tool(self, tool_name: str, params: dict, company_id: int = None):
        # The "listen" tool is a special case that signals a pause.
        if tool_name == "listen_for_input":
            return {"status": "paused_for_input"}
        
        # The "prompt" tool signals a pause and sends data to the frontend.
        if tool_name == "prompt_for_input":
            return {
                "status": "paused_for_prompt",
                "prompt": {
                    "text": params.get("prompt_text", "Please provide input."),
                    "options": params.get("options", [])
                }
            }

        if tool_name == "llm_tool":
            # ... (existing llm_tool logic)
            return {"output": "LLM response"} # Placeholder

        tool = self.db.query(Tool).filter(Tool.name == tool_name).first()
        if not tool:
            return {"error": f"Tool '{tool_name}' not found."}

        execution_scope = {"db": self.db}
        try:
            exec(tool.code, execution_scope)
            tool_function = execution_scope.get("run")
            if not callable(tool_function):
                return {"error": "Tool code does not define a callable 'run' function"}
            
            config = {"db": self.db}
            result = tool_function(params=params, config=config)
            return {"output": result}
        except Exception as e:
            return {"error": f"Error executing tool {tool_name}: {e}"}

    def _resolve_placeholders(self, value: str, context: dict, results: dict):
        """Resolves placeholders like {{context.variable}} or {{step_id.output}}."""
        if not isinstance(value, str) or '{{' not in value:
            return value

        print(f"DEBUG: Resolving placeholders in: '{value}'")

        def replace_func(match):
            placeholder = match.group(1).strip()
            print(f"  - Found placeholder: {placeholder}")
            path = placeholder.split(".")
            source = path[0]
            
            resolved_value = ''
            if source == "context":
                key = path[1]
                resolved_value = context.get(key, '')
                print(f"    - Source: context, Key: {key}, Value: '{resolved_value}'")
            else:
                # Handle results from previous nodes
                step_result = results.get(source)
                print(f"    - Source: results, Step: {source}, Result: {step_result}")
                if step_result:
                    # Drill down to find the actual output value
                    output_value = step_result.get("output")
                    if isinstance(output_value, dict):
                        # Handle nested results like from an LLM call
                        resolved_value = output_value.get("content", '')
                    elif output_value is None:
                        resolved_value = ''
                    else:
                        resolved_value = output_value
                print(f"    - Resolved value: '{resolved_value}'")

            return str(resolved_value)

        resolved_string = re.sub(r"\{\{(.*?)\}\}", replace_func, value)
        print(f"DEBUG: Final resolved string: '{resolved_string}'")
        return resolved_string

    def _execute_data_manipulation_node(self, node_data: dict, context: dict, results: dict):
        expression = node_data.get("expression", "")
        output_variable = node_data.get("output_variable", "output")

        # Create a safe execution environment for eval
        safe_globals = {"__builtins__": None}
        safe_locals = {"context": context, "results": results}

        try:
            # Resolve placeholders in the expression before evaluation
            resolved_expression = self._resolve_placeholders(expression, context, results)
            
            # Evaluate the expression
            manipulated_data = eval(resolved_expression, safe_globals, safe_locals)
            
            # Store the result in the context
            context[output_variable] = manipulated_data
            
            return {"output": manipulated_data}
        except Exception as e:
            return {"error": f"Error manipulating data: {e}"}

    def _execute_code_node(self, node_data: dict, context: dict, results: dict):
        code = node_data.get("code", "")
        resolved_code = self._resolve_placeholders(code, context, results)

        execution_scope = {
            "context": context,
            "results": results,
            "db": self.db,
            "output": None # To capture the output of the code
        }
        try:
            exec(resolved_code, execution_scope)
            return {"output": execution_scope.get("output", "Code executed successfully.")}
        except Exception as e:
            return {"error": f"Error executing code: {e}"}

    def _execute_knowledge_retrieval_node(self, node_data: dict, context: dict, results: dict):
        knowledge_base_id = node_data.get("knowledge_base_id")
        query = node_data.get("query", "")
        resolved_query = self._resolve_placeholders(query, context, results)

        if not knowledge_base_id:
            return {"error": "Knowledge Base ID is required for knowledge retrieval node."}

        try:
            # Assuming knowledge_base_service.query_knowledge_base exists and returns relevant documents
            retrieved_docs = knowledge_base_service.query_knowledge_base(self.db, knowledge_base_id, resolved_query)
            # Format the retrieved documents as a string or a list of strings
            formatted_docs = "\n\n".join([doc.content for doc in retrieved_docs]) # Adjust based on actual doc structure
            return {"output": formatted_docs}
        except Exception as e:
            return {"error": f"Error retrieving knowledge: {e}"}

    def _execute_conditional_node(self, node_data: dict, context: dict, results: dict):
        variable_placeholder = node_data.get("variable", "")
        operator = node_data.get("operator", "equals")
        comparison_value = node_data.get("value", "")

        # Resolve the variable placeholder to get the actual value from the context or results
        actual_value = self._resolve_placeholders(variable_placeholder, context, results)

        print(f"DEBUG: Executing conditional node:")
        print(f"  - Variable '{variable_placeholder}' resolved to: '{actual_value}' (type: {type(actual_value)})")
        print(f"  - Operator: '{operator}'")
        print(f"  - Comparison Value: '{comparison_value}' (type: {type(comparison_value)})")

        # Coerce types for comparison where possible
        try:
            # Try to convert comparison_value to the type of actual_value if it's a number
            if isinstance(actual_value, (int, float)):
                comparison_value = type(actual_value)(comparison_value)
        except (ValueError, TypeError):
            # If conversion fails, proceed with string comparison
            pass

        result = False
        if operator == "equals":
            result = actual_value == comparison_value
        elif operator == "not_equals":
            result = actual_value != comparison_value
        elif operator == "contains":
            result = str(comparison_value) in str(actual_value)
        elif operator == "greater_than":
            try:
                result = float(actual_value) > float(comparison_value)
            except (ValueError, TypeError):
                result = False # Cannot compare non-numeric values
        elif operator == "less_than":
            try:
                result = float(actual_value) < float(comparison_value)
            except (ValueError, TypeError):
                result = False # Cannot compare non-numeric values
        elif operator == "is_set":
            result = actual_value is not None and actual_value != ''
        elif operator == "is_not_set":
            result = actual_value is None or actual_value == ''
        
        print(f"  - Condition evaluated to: {result}")
        return {"output": result}

    def _execute_http_request_node(self, node_data: dict, context: dict, results: dict):
        url = node_data.get("url", "")
        method = node_data.get("method", "GET").upper()
        headers_str = node_data.get("headers", "{}")
        body_str = node_data.get("body", "{}")

        resolved_url = self._resolve_placeholders(url, context, results)
        resolved_headers_str = self._resolve_placeholders(headers_str, context, results)
        resolved_body_str = self._resolve_placeholders(body_str, context, results)

        try:
            headers = json.loads(resolved_headers_str)
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON in headers: {resolved_headers_str}"}

        try:
            body = json.loads(resolved_body_str) if method in ["POST", "PUT"] else None
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON in body: {resolved_body_str}"}

        try:
            response = None
            if method == "GET":
                response = requests.get(resolved_url, headers=headers)
            elif method == "POST":
                response = requests.post(resolved_url, headers=headers, json=body)
            elif method == "PUT":
                response = requests.put(resolved_url, headers=headers, json=body)
            elif method == "DELETE":
                response = requests.delete(resolved_url, headers=headers)
            else:
                return {"error": f"Unsupported HTTP method: {method}"}

            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            return {"output": response.json() if response.headers.get('Content-Type') == 'application/json' else response.text}
        except requests.exceptions.RequestException as e:
            return {"error": f"HTTP request failed: {e}"}
        except Exception as e:
            return {"error": f"Error executing HTTP request node: {e}"}

    def _execute_llm_node(self, node_data: dict, context: dict, results: dict, company_id: int, workflow, conversation_id: str):
        prompt = node_data.get("prompt", "")
        resolved_prompt = self._resolve_placeholders(prompt, context, results)

        # 1. Get the system prompt from the agent associated with the workflow
        system_prompt = workflow.agent.prompt if workflow.agent else "You are a helpful assistant."

        # 2. Get the chat history
        chat_history = []
        if conversation_id:
            # Assuming a function exists to get chat messages by conversation_id
            # This might need to be created in chat_service.py
            history_messages = conversation_session_service.get_chat_history(self.db, conversation_id)
            for msg in history_messages:
                role = "assistant" if msg.sender == "agent" else msg.sender
                chat_history.append({"role": role, "content": msg.message})

        # 3. Get the tools associated with the agent
        agent_tools = workflow.agent.tools if workflow.agent else []

        llm_response = self.llm_tool_service.execute(
            model=node_data.get("model"),
            system_prompt=system_prompt,
            chat_history=chat_history,
            user_prompt=resolved_prompt,
            tools=agent_tools,
            knowledge_base_id=node_data.get("knowledge_base_id"),
            company_id=company_id
        )

        return {"output": llm_response}

    def execute_workflow(self, user_message: str, company_id: int, workflow_id: int = None, workflow: Workflow = None, conversation_id: str = None):
        if workflow_id:
            workflow_obj = workflow_service.get_workflow(self.db, workflow_id, company_id)
        elif workflow:
            workflow_obj = workflow
        else:
            return {"error": "Either workflow_id or workflow object must be provided."}

        if not workflow_obj:
            return {"error": f"Workflow not found."}

        print(f"DEBUG: Fetched workflow: {workflow_obj.name} (ID: {workflow_obj.id})")
        if hasattr(workflow_obj, 'agent') and workflow_obj.agent:
            print(f"DEBUG: Workflow agent: {workflow_obj.agent.name} (ID: {workflow_obj.agent.id})")
            print(f"DEBUG: Workflow agent company_id: {workflow_obj.agent.company_id}")
        else:
            print("DEBUG: Workflow agent is None or not loaded.")
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        session = conversation_session_service.get_or_create_session(
            self.db, conversation_id, workflow_obj.id, contact_id=1, channel="test", company_id=workflow_obj.agent.company_id
        )

        context = session.context or {}
        results = {}

        # Ensure visual_steps is a dictionary
        visual_steps_data = workflow_obj.visual_steps
        if isinstance(visual_steps_data, str):
            try:
                visual_steps_data = json.loads(visual_steps_data)
            except json.JSONDecodeError:
                return {"error": "Failed to parse workflow visual steps."}
        
        graph_engine = GraphExecutionEngine(visual_steps_data)
        
        if session.status == 'paused' and session.next_step_id:
            current_node_id = session.next_step_id
            # The user_message is the result of the paused step
            result_from_pause = {"output": user_message}
            
            # Find the node that caused the pause to get the variable name
            previous_node_id = None
            for node_id, node_info in graph_engine.nodes.items():
                # Check if this node's next step on success is the paused step
                # This is a simplification; a more robust way might be needed for complex graphs
                next_node_in_graph = graph_engine.get_next_node(node_id, result_from_pause)
                if next_node_in_graph == session.next_step_id:
                    previous_node_id = node_id
                    break
            
            if previous_node_id:
                previous_node = graph_engine.nodes[previous_node_id]
                if previous_node.get('type') in ['listen', 'prompt', 'form']:
                    output_variable = previous_node.get('data', {}).get('params', {}).get('save_to_variable')
                    if output_variable:
                        context[output_variable] = user_message
        else:
            current_node_id = graph_engine.find_start_node()

        last_executed_node_id = None
        while current_node_id:
            node = graph_engine.nodes[current_node_id]
            node_type = node.get("type")
            node_data = node.get("data", {})

            result = None
            if node_type == "start":
                initial_input_variable = node_data.get("initial_input_variable", "user_message")
                context[initial_input_variable] = user_message
                result = {"output": "Start node processed"} # Indicate success, no real output
            elif node_type == "tool":
                tool_name = node_data.get("tool_name")
                raw_params = node_data.get("parameters", {})
                resolved_params = {k: self._resolve_placeholders(v, context, results) for k, v in raw_params.items()}
                result = self._execute_tool(tool_name, resolved_params, company_id=workflow.agent.company_id)

            elif node_type == "http_request":
                result = self._execute_http_request_node(node_data, context, results)

            elif node_type == "llm":
                result = self._execute_llm_node(node_data, context, results, company_id=workflow.agent.company_id, workflow=workflow, conversation_id=conversation_id)

            elif node_type == "data_manipulation":
                result = self._execute_data_manipulation_node(node_data, context, results)

            elif node_type == "code":
                result = self._execute_code_node(node_data, context, results)

            elif node_type == "knowledge":
                result = self._execute_knowledge_retrieval_node(node_data, context, results)

            elif node_type == "condition":
                result = self._execute_conditional_node(node_data, context, results)

            elif node_type == "listen":
                result = {"status": "paused_for_input"}

            elif node_type == "prompt":
                params = node_data.get("params", {})
                options_str = params.get("options", "")
                options_list = [opt.strip() for opt in options_str.split(',')] if options_str else []
                result = {
                    "status": "paused_for_prompt",
                    "prompt": {
                        "text": params.get("prompt_text", "Please provide input."),
                        "options": options_list
                    }
                }
            
            elif node_type == "form":
                params = node_data.get("params", {})
                result = {
                    "status": "paused_for_form",
                    "form": {
                        "title": params.get("title", "Please fill out this form."),
                        "fields": params.get("fields", [])
                    }
                }

            elif node_type == "output":
                output_value = node_data.get("output_value", "")
                resolved_output = self._resolve_placeholders(output_value, context, results)
                result = {"output": resolved_output}

            results[current_node_id] = result
            last_executed_node_id = current_node_id

            if result and result.get("status") in ["paused_for_input", "paused_for_prompt", "paused_for_form"]:
                next_node_id = graph_engine.get_next_node(current_node_id, result)
                session_update = ConversationSessionUpdate(
                    next_step_id=next_node_id,
                    context=context,
                    status='paused'
                )
                conversation_session_service.update_session(self.db, conversation_id, session_update)
                
                response_payload = {
                    "status": result.get("status"),
                    "conversation_id": conversation_id,
                    "next_node_id": next_node_id
                }
                if "prompt" in result:
                    response_payload["prompt"] = result["prompt"]
                if "form" in result:
                    response_payload["form"] = result["form"]
                
                return response_payload

            if result and "error" in result:
                # The get_next_node method will handle routing to the error path if it exists
                pass

            print(f"DEBUG: About to call get_next_node for node '{current_node_id}' with result: {result}")
            current_node_id = graph_engine.get_next_node(current_node_id, result)
            print(f"DEBUG: get_next_node returned: {current_node_id}")

        # Finalizing the workflow
        session_update = ConversationSessionUpdate(status='completed', context=context)
        conversation_session_service.update_session(self.db, conversation_id, session_update)

        final_output = results.get(last_executed_node_id, {}).get("output", "Workflow completed.")
        return {"status": "completed", "response": final_output, "conversation_id": conversation_id}
