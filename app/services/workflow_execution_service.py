import json
import re
import uuid
import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from app.models import workflow
from app.models.workflow import Workflow
from app.models.tool import Tool
from app.services import tool_service, conversation_session_service, knowledge_base_service, workflow_service, memory_service
from app.schemas.conversation_session import ConversationSessionUpdate
from app.schemas.memory import MemoryCreate
from app.services.graph_execution_engine import GraphExecutionEngine
from app.services.llm_tool_service import LLMToolService
from app.services.workflow_intent_service import WorkflowIntentService
from app.core.config import settings

import httpx
import numexpr


class WorkflowExecutionService:
    def __init__(self, db: Session):
        self.db = db
        self.llm_tool_service = LLMToolService(db)
        self.workflow_intent_service = WorkflowIntentService(db)

    async def _execute_tool(self, tool_name: str, params: dict, company_id: int = None, session_id: str = None):
        """
        Execute a tool using the unified tool execution service.
        Supports builtin, custom, and MCP tools.
        """
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

        # Use unified tool execution for all tool types (builtin, custom, MCP)
        from app.services import tool_execution_service

        result = await tool_execution_service.execute_tool(
            db=self.db,
            tool_name=tool_name,
            parameters=params,
            session_id=session_id,
            company_id=company_id
        )

        if result is None:
            return {"error": f"Tool '{tool_name}' not found."}

        # Normalize result format for workflow engine
        if "result" in result:
            return {"output": result["result"]}
        return result

    def _resolve_placeholders(self, value: str, context: dict, results: dict):
        """Resolves placeholders like {{context.variable}}, {{context.obj.key}}, or {{step_id.output}}."""
        if not isinstance(value, str) or '{{' not in value:
            return value

        print(f"DEBUG: Resolving placeholders in: '{value}' with context: {context}")

        def drill_down(obj, keys):
            """Helper to drill down into nested objects/dicts."""
            for key in keys:
                if isinstance(obj, dict):
                    obj = obj.get(key, '')
                else:
                    return ''
            return obj

        def resolve_single_placeholder(placeholder: str):
            """Resolve a single placeholder and return the actual value (preserving type)."""
            path = placeholder.split(".")
            source = path[0]

            resolved_value = ''
            if source == "context":
                remaining_path = path[1:]
                resolved_value = drill_down(context, remaining_path)
                print(f"    - Source: context, Path: {remaining_path}, Value: '{resolved_value}'")
            else:
                step_result = results.get(source)
                print(f"    - Source: results, Step: {source}, Result: {step_result}")
                if step_result:
                    remaining_path = path[1:]
                    resolved_value = drill_down(step_result, remaining_path) if remaining_path else step_result

                    if not remaining_path:
                        output_value = step_result.get("output")
                        if isinstance(output_value, dict):
                            resolved_value = output_value.get("content", '')
                        elif output_value is None:
                            resolved_value = ''
                        else:
                            resolved_value = output_value
                print(f"    - Resolved value: '{resolved_value}'")

            return resolved_value

        # Check if the entire value is a single placeholder (e.g., "{{code-123.output.show_dict}}")
        # If so, return the actual value (dict, list, etc.) instead of converting to string
        # Use [^{}]+ to ensure we don't match strings with multiple placeholders
        single_placeholder_match = re.match(r"^\s*\{\{([^{}]+)\}\}\s*$", value)
        if single_placeholder_match:
            placeholder = single_placeholder_match.group(1).strip()
            print(f"  - Found single placeholder: {placeholder}")
            resolved = resolve_single_placeholder(placeholder)
            print(f"DEBUG: Returning actual value (type: {type(resolved).__name__}): {resolved}")
            return resolved

        # For embedded placeholders in text, convert to strings
        def replace_func(match):
            placeholder = match.group(1).strip()
            print(f"  - Found placeholder: {placeholder}")
            resolved_value = resolve_single_placeholder(placeholder)
            return str(resolved_value) if resolved_value is not None else ''

        resolved_string = re.sub(r"\{\{(.*?)\}\}", replace_func, value)
        print(f"DEBUG: Final resolved string: '{resolved_string}'")
        return resolved_string

    async def _execute_data_manipulation_node(self, node_data: dict, context: dict, results: dict):
        from types import SimpleNamespace

        expression = node_data.get("expression", "")
        output_variable = node_data.get("output_variable", "output")

        # Helper function to convert nested dicts to SimpleNamespace for dot notation access
        def dict_to_namespace(d):
            if isinstance(d, dict):
                return SimpleNamespace(**{k: dict_to_namespace(v) for k, v in d.items()})
            elif isinstance(d, list):
                return [dict_to_namespace(item) for item in d]
            return d

        # Create namespace versions for dot notation access
        context_ns = dict_to_namespace(context)
        results_ns = dict_to_namespace(results)

        # Create a safe execution environment for eval
        # Allow both dict access (context['key']) and dot notation (context.key)
        safe_globals = {"__builtins__": None}
        safe_locals = {
            "context": context_ns,  # Dot notation access
            "ctx": context,         # Dict access alternative
            "results": results_ns,  # Dot notation access
            "res": results          # Dict access alternative
        }

        try:
            # Resolve placeholders in the expression before evaluation
            resolved_expression = self._resolve_placeholders(expression, context, results)

            # Run eval in thread pool to avoid blocking the event loop
            def run_eval():
                return eval(resolved_expression, safe_globals, safe_locals)

            manipulated_data = await asyncio.to_thread(run_eval)

            # Store the result in the context
            context[output_variable] = manipulated_data

            return {"output": manipulated_data}
        except Exception as e:
            return {"error": f"Error manipulating data: {e}"}

    async def _execute_code_node(self, node_data: dict, context: dict, results: dict):
        code = node_data.get("code", "")
        arguments = node_data.get("arguments", [])  # [{name: "arg1", value: "{{context.var}}"}]
        return_variables = node_data.get("return_variables", [])  # ["result1", "result2"]

        # Resolve argument values from placeholders
        resolved_args = {}
        arg_names_ordered = []  # Keep track of argument order for function calls
        for arg in arguments:
            arg_name = arg.get("name", "")
            arg_value = arg.get("value", "")
            if arg_name:
                resolved_value = self._resolve_placeholders(str(arg_value), context, results)
                # If resolved_value is already a dict/list, use it directly
                if isinstance(resolved_value, (dict, list)):
                    resolved_args[arg_name] = resolved_value
                # Try to parse as Python literal if it looks like a dict/list string
                elif isinstance(resolved_value, str) and (resolved_value.startswith('{') or resolved_value.startswith('[')):
                    try:
                        import ast
                        resolved_args[arg_name] = ast.literal_eval(resolved_value)
                    except (ValueError, SyntaxError):
                        resolved_args[arg_name] = resolved_value
                else:
                    resolved_args[arg_name] = resolved_value
                arg_names_ordered.append(arg_name)

        print(f"[CODE NODE] Arguments: {resolved_args}, Return vars: {return_variables}")

        # Build execution scope with arguments directly available
        execution_scope = {
            "context": context,
            "results": results,
            "db": self.db,
            "output": None,  # Legacy support for setting output directly
            **resolved_args  # Spread arguments into scope so they're directly accessible
        }

        # Define synchronous code execution function to run in thread pool
        def run_code_sync():
            try:
                # Execute the code
                exec(code, execution_scope)

                # Check if a function was defined and should be auto-called
                # Only auto-call if the function wasn't already called in the code
                import re
                func_match = re.search(r'def\s+(\w+)\s*\(', code)
                if func_match:
                    func_name = func_match.group(1)
                    # Check if function was manually called in the code (look for "func_name(" after the def block)
                    func_call_pattern = rf'{func_name}\s*\('
                    # Find all calls - if there's a call outside the def, user called it manually
                    func_def_end = code.find('def ' + func_name)
                    code_after_def = code[func_def_end:] if func_def_end >= 0 else ""
                    # Check if there's a call that's not the def line itself
                    lines_after_def = code_after_def.split('\n')[1:]  # Skip the def line
                    manual_call_exists = any(re.search(func_call_pattern, line) and not line.strip().startswith('def ') for line in lines_after_def)

                    # Also check if return variables are already set (user assigned them manually)
                    return_vars_already_set = return_variables and all(
                        var_name.strip() in execution_scope and execution_scope[var_name.strip()] is not None
                        for var_name in return_variables if var_name.strip()
                    )

                    if not manual_call_exists and not return_vars_already_set:
                        if func_name in execution_scope and callable(execution_scope[func_name]):
                            # Call the function with arguments in order
                            func = execution_scope[func_name]
                            arg_values = [resolved_args[name] for name in arg_names_ordered if name in resolved_args]
                            print(f"[CODE NODE] Auto-calling function '{func_name}' with args: {arg_values}")
                            func_result = func(*arg_values)

                            # If there's one return variable, assign the function result to it
                            if return_variables and len(return_variables) == 1:
                                var_name = return_variables[0].strip()
                                execution_scope[var_name] = func_result
                                context[var_name] = func_result
                                print(f"[CODE NODE] Output: {{{var_name}: {func_result}}}")
                                return {"output": {var_name: func_result}}
                            elif return_variables and len(return_variables) > 1 and isinstance(func_result, (tuple, list)):
                                # Multiple return values
                                output = {}
                                for i, var_name in enumerate(return_variables):
                                    var_name = var_name.strip()
                                    if i < len(func_result):
                                        output[var_name] = func_result[i]
                                        context[var_name] = func_result[i]
                                print(f"[CODE NODE] Output: {output}")
                                return {"output": output if output else func_result}
                            else:
                                # No return variables defined, just return the function result
                                print(f"[CODE NODE] Output: {func_result}")
                                return {"output": func_result}

                # Collect return variables into output (for non-function code or manually called functions)
                if return_variables:
                    output = {}
                    for var_name in return_variables:
                        var_name = var_name.strip()
                        if var_name and var_name in execution_scope:
                            output[var_name] = execution_scope[var_name]
                            # Also store in context for later use in workflow
                            context[var_name] = execution_scope[var_name]

                    print(f"[CODE NODE] Output: {output}")
                    return {"output": output if output else "Code executed successfully."}
                else:
                    # Legacy behavior: return the 'output' variable if set
                    return {"output": execution_scope.get("output", "Code executed successfully.")}

            except Exception as e:
                import traceback
                print(f"[CODE NODE] Error: {e}")
                return {"error": f"Error executing code: {e}", "traceback": traceback.format_exc()}

        # Run the synchronous code execution in a thread pool to avoid blocking the event loop
        return await asyncio.to_thread(run_code_sync)

    async def _execute_knowledge_retrieval_node(self, node_data: dict, context: dict, results: dict, company_id: int, workflow):
        knowledge_base_id = node_data.get("knowledge_base_id")
        query = node_data.get("query", "")
        resolved_query = self._resolve_placeholders(query, context, results)

        if not knowledge_base_id:
            return {"error": "Knowledge Base ID is required for knowledge retrieval node."}

        try:
            # Find relevant chunks from knowledge base (pass agent for correct embedding model)
            retrieved_chunks = knowledge_base_service.find_relevant_chunks(
                self.db, knowledge_base_id, company_id, resolved_query, top_k=5,
                agent=workflow.agent if workflow else None
            )

            if not retrieved_chunks:
                return {"output": "I couldn't find any relevant information for your query."}

            # Format chunks as human-readable text (without LLM call)
            # Join chunks with separators for readability
            formatted_response = "\n\n---\n\n".join(retrieved_chunks)

            return {"output": formatted_response}

        except Exception as e:
            return {"error": f"Error retrieving knowledge: {e}"}

    def _evaluate_single_condition(self, variable_placeholder: str, operator: str, comparison_value: str, context: dict, results: dict) -> bool:
        """Evaluate a single condition and return True/False."""
        # Resolve the variable placeholder to get the actual value from the context or results
        actual_value = self._resolve_placeholders(variable_placeholder, context, results)

        print(f"    - Variable '{variable_placeholder}' resolved to: '{actual_value}' (type: {type(actual_value)})")
        print(f"    - Operator: '{operator}', Comparison Value: '{comparison_value}'")

        # Coerce types for comparison where possible
        try:
            if isinstance(actual_value, (int, float)):
                comparison_value = type(actual_value)(comparison_value)
        except (ValueError, TypeError):
            pass

        result = False
        if operator == "equals":
            if isinstance(actual_value, str) and isinstance(comparison_value, str):
                result = actual_value.lower().strip() == comparison_value.lower().strip()
            else:
                result = actual_value == comparison_value
        elif operator == "not_equals":
            if isinstance(actual_value, str) and isinstance(comparison_value, str):
                result = actual_value.lower().strip() != comparison_value.lower().strip()
            else:
                result = actual_value != comparison_value
        elif operator == "contains":
            result = str(comparison_value).lower() in str(actual_value).lower()
        elif operator == "greater_than":
            try:
                result = float(actual_value) > float(comparison_value)
            except (ValueError, TypeError):
                result = False
        elif operator == "less_than":
            try:
                result = float(actual_value) < float(comparison_value)
            except (ValueError, TypeError):
                result = False
        elif operator == "is_set":
            result = actual_value is not None and actual_value != ''
        elif operator == "is_not_set":
            result = actual_value is None or actual_value == ''

        print(f"    - Result: {result}")
        return result

    def _execute_conditional_node(self, node_data: dict, context: dict, results: dict):
        """
        Execute a conditional node with support for multiple conditions (if/elseif/else).

        Supports two formats:
        1. Legacy single condition: {"variable": "...", "operator": "...", "value": "..."}
           - Returns {"output": True/False} for true/false handles

        2. Multi-condition: {"conditions": [{"variable": "...", "operator": "...", "value": "..."}, ...]}
           - Returns {"output": index} for the first matching condition (handle "0", "1", "2", etc.)
           - Returns {"output": "else"} if no condition matches (handle "else")
        """
        conditions = node_data.get("conditions", [])

        # Check if using new multi-condition format
        if conditions and isinstance(conditions, list) and len(conditions) > 0:
            print(f"DEBUG: Executing multi-condition node with {len(conditions)} conditions:")

            for index, condition in enumerate(conditions):
                variable = condition.get("variable", "")
                operator = condition.get("operator", "equals")
                value = condition.get("value", "")

                print(f"  Condition {index} (handle '{index}'):")
                if self._evaluate_single_condition(variable, operator, value, context, results):
                    print(f"  ✓ Condition {index} matched! Routing to handle '{index}'")
                    return {"output": index}  # Return index for routing

            # No condition matched, return else
            print(f"  ✗ No conditions matched. Routing to 'else' handle")
            return {"output": "else"}

        else:
            # Legacy single condition format (backward compatible)
            variable_placeholder = node_data.get("variable", "")
            operator = node_data.get("operator", "equals")
            comparison_value = node_data.get("value", "")

            print(f"DEBUG: Executing single conditional node:")
            result = self._evaluate_single_condition(variable_placeholder, operator, comparison_value, context, results)
            print(f"  - Condition evaluated to: {result}")
            return {"output": result}

    async def _execute_http_request_node(self, node_data: dict, context: dict, results: dict):
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
            body = json.loads(resolved_body_str) if method in ["POST", "PUT", "PATCH"] else None
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON in body: {resolved_body_str}"}

        try:
            async with httpx.AsyncClient(timeout=settings.HTTP_REQUEST_TIMEOUT) as client:
                response = None
                if method == "GET":
                    response = await client.get(resolved_url, headers=headers)
                elif method == "POST":
                    response = await client.post(resolved_url, headers=headers, json=body)
                elif method == "PUT":
                    response = await client.put(resolved_url, headers=headers, json=body)
                elif method == "PATCH":
                    response = await client.patch(resolved_url, headers=headers, json=body)
                elif method == "DELETE":
                    response = await client.delete(resolved_url, headers=headers)
                else:
                    return {"error": f"Unsupported HTTP method: {method}"}

                response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' in content_type:
                    return {"output": response.json()}
                else:
                    return {"output": response.text}
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
        except httpx.RequestError as e:
            return {"error": f"HTTP request failed: {e}"}
        except Exception as e:
            return {"error": f"Error executing HTTP request: {e}"}

    async def _execute_llm_node(self, node_data: dict, context: dict, results: dict, company_id: int, workflow, conversation_id: str):
        prompt = node_data.get("prompt", "")
        resolved_prompt = self._resolve_placeholders(prompt, context, results)

        # 1. Get the system prompt - use custom if provided, otherwise fall back to agent's prompt
        custom_system_prompt = node_data.get("system_prompt", "")
        if custom_system_prompt:
            # Resolve any placeholders in the custom system prompt
            system_prompt = self._resolve_placeholders(custom_system_prompt, context, results)
        else:
            # Fall back to agent's system prompt
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

        # 4. Get attachments from context (for vision model support)
        # Only include attachments if agent has vision_enabled
        attachments = []
        if workflow.agent and getattr(workflow.agent, 'vision_enabled', False):
            # First check user_attachments (set during workflow execution)
            attachments = context.get("user_attachments", [])

            # Also check if any context variable contains attachments (from Listen node)
            # This handles cases where Listen node saved {text, attachments} format
            if not attachments:
                for key, value in context.items():
                    if isinstance(value, dict) and "attachments" in value:
                        attachments = value.get("attachments", [])
                        if attachments:
                            print(f"DEBUG: Found attachments in context variable '{key}'")
                            break
        else:
            print(f"DEBUG: Vision not enabled for agent, skipping attachments")

        llm_response = await self.llm_tool_service.execute(
            model=node_data.get("model"),
            system_prompt=system_prompt,
            chat_history=chat_history,
            user_prompt=resolved_prompt,
            tools=agent_tools,
            knowledge_base_id=node_data.get("knowledge_base_id"),
            company_id=company_id,
            attachments=attachments
        )

        # Extract the content from the LLM response
        if isinstance(llm_response, dict):
            response_text = llm_response.get("content", "")
        else:
            response_text = str(llm_response)

        return {"output": response_text}

    # ============================================================
    # NEW CHAT-SPECIFIC NODE EXECUTION METHODS
    # ============================================================

    def _execute_intent_router_node(self, node_data: dict, context: dict, results: dict):
        """
        Routes workflow based on detected intent in context.
        Returns intent_name to determine which edge to follow.
        """
        detected_intent = context.get("detected_intent")
        intent_confidence = context.get("intent_confidence", 0.0)

        routes = node_data.get("routes", [])

        # Check if detected intent matches any configured route
        for route in routes:
            intent_name = route.get("intent_name")
            min_confidence = route.get("min_confidence", 0.7)

            if detected_intent == intent_name and intent_confidence >= min_confidence:
                print(f"✓ Intent router: Routing to '{intent_name}' (confidence: {intent_confidence:.2f})")
                return {
                    "output": intent_name,
                    "route": intent_name,
                    "confidence": intent_confidence
                }

        # No matching route, use default
        print(f"✓ Intent router: Using default route (no intent match)")
        return {
            "output": "default",
            "route": "default",
            "confidence": 0.0
        }

    async def _execute_entity_collector_node(
        self, node_data: dict, context: dict, results: dict, workflow: Workflow, conversation_id: str
    ):
        """
        Collects required entities from context or prompts user for missing ones.
        """
        entities_to_collect = node_data.get("entities_to_collect", [])
        collection_strategy = node_data.get("collection_strategy", "ask_if_missing")
        prompts = node_data.get("prompts", {})
        max_attempts = node_data.get("max_attempts", 3)

        missing_entities = []
        collected_entities = {}

        # Check which entities are already in context
        for entity_name in entities_to_collect:
            if entity_name in context and context[entity_name]:
                collected_entities[entity_name] = context[entity_name]
                print(f"✓ Entity '{entity_name}' already in context: {context[entity_name]}")
            else:
                missing_entities.append(entity_name)
                print(f"✗ Entity '{entity_name}' missing from context")

        if not missing_entities:
            # All entities collected
            return {
                "output": collected_entities,
                "status": "complete",
                "collected": collected_entities
            }

        if collection_strategy == "extract_only":
            # Don't prompt, just return what we have
            return {
                "output": collected_entities,
                "status": "partial",
                "collected": collected_entities,
                "missing": missing_entities
            }

        # Ask for first missing entity
        first_missing = missing_entities[0]
        prompt_text = prompts.get(first_missing, f"Please provide your {first_missing}")

        print(f"ℹ Prompting user for entity '{first_missing}'")

        return {
            "status": "paused_for_prompt",
            "prompt": {
                "text": prompt_text,
                "options": []
            },
            "collecting_entity": first_missing,
            "remaining_entities": missing_entities
        }

    def _execute_check_entity_node(self, node_data: dict, context: dict, results: dict):
        """
        Checks if a specific entity exists in context.
        Returns boolean for routing (true/false edges).
        """
        entity_name = node_data.get("entity_name")
        check_type = node_data.get("check_type", "exists")  # exists, not_empty, valid

        entity_value = context.get(entity_name)

        if check_type == "exists":
            has_entity = entity_name in context
        elif check_type == "not_empty":
            has_entity = entity_name in context and entity_value not in [None, "", []]
        elif check_type == "valid":
            # Could add regex validation here
            validation_regex = node_data.get("validation_regex")
            if validation_regex and entity_value:
                import re
                has_entity = bool(re.match(validation_regex, str(entity_value)))
            else:
                has_entity = entity_name in context and entity_value is not None
        else:
            has_entity = False

        print(f"✓ Check entity '{entity_name}': {has_entity} (value: {entity_value})")

        return {
            "output": has_entity,
            "entity_name": entity_name,
            "entity_value": entity_value,
            "check_result": has_entity
        }

    def _execute_update_context_node(self, node_data: dict, context: dict, results: dict):
        """
        Updates context with new variables or values.
        """
        variables = node_data.get("variables", {})

        updated_vars = {}
        for var_name, var_value in variables.items():
            # Resolve placeholders in value
            resolved_value = self._resolve_placeholders(str(var_value), context, results)
            context[var_name] = resolved_value
            updated_vars[var_name] = resolved_value
            print(f"✓ Updated context: {var_name} = {resolved_value}")

        return {
            "output": "Context updated",
            "updated_variables": updated_vars
        }

    def _execute_tag_conversation_node(self, node_data: dict, context: dict, results: dict, conversation_id: str):
        """
        Adds tags to the conversation for organization and filtering.
        """
        tags = node_data.get("tags", [])

        # Resolve any placeholders in tags
        resolved_tags = []
        for tag in tags:
            resolved_tag = self._resolve_placeholders(str(tag), context, results)
            resolved_tags.append(resolved_tag)

        # Update conversation session with tags
        try:
            session = conversation_session_service.get_session(self.db, conversation_id)
            if session:
                current_tags = session.context.get("tags", []) if session.context else []
                updated_tags = list(set(current_tags + resolved_tags))  # Remove duplicates

                session_context = session.context or {}
                session_context["tags"] = updated_tags

                conversation_session_service.update_session_context(
                    self.db, conversation_id, session_context
                )

                print(f"✓ Added tags to conversation: {resolved_tags}")

                return {
                    "output": "Tags added",
                    "tags_added": resolved_tags,
                    "all_tags": updated_tags
                }
        except Exception as e:
            print(f"✗ Error adding tags: {e}")
            return {"error": f"Failed to add tags: {e}"}

    def _execute_assign_to_agent_node(
        self, node_data: dict, context: dict, results: dict, conversation_id: str, company_id: int
    ):
        """
        Assigns the conversation to a human agent or agent pool.
        """
        assignment_type = node_data.get("assignment_type", "pool")  # pool, specific, round_robin
        agent_id = node_data.get("agent_id")
        pool_name = node_data.get("pool_name", "support")
        priority = node_data.get("priority", "normal")
        notes = node_data.get("notes", "")

        resolved_notes = self._resolve_placeholders(notes, context, results)

        try:
            session = conversation_session_service.get_session(self.db, conversation_id)
            if session:
                # Update status for agent assignment (AI stays enabled - can be toggled manually)
                session_update = ConversationSessionUpdate(
                    status='pending_agent_assignment'
                )
                conversation_session_service.update_session(self.db, conversation_id, session_update)

                # Store assignment info in context
                assignment_info = {
                    "assigned_at": datetime.now().isoformat(),
                    "assignment_type": assignment_type,
                    "pool": pool_name,
                    "priority": priority,
                    "notes": resolved_notes
                }

                if agent_id:
                    assignment_info["agent_id"] = agent_id

                session_context = session.context or {}
                session_context["assignment"] = assignment_info
                conversation_session_service.update_session_context(
                    self.db, conversation_id, session_context
                )

                print(f"✓ Assigned conversation to {assignment_type}: {pool_name or agent_id}")

                return {
                    "output": "Assigned to agent",
                    "assignment": assignment_info
                }
        except Exception as e:
            print(f"✗ Error assigning to agent: {e}")
            return {"error": f"Failed to assign to agent: {e}"}

    def _execute_set_status_node(self, node_data: dict, context: dict, results: dict, conversation_id: str):
        """
        Sets the conversation status (e.g., resolved, pending, escalated).
        """
        status = node_data.get("status", "active")
        reason = node_data.get("reason", "")

        resolved_reason = self._resolve_placeholders(reason, context, results)

        try:
            session_update = ConversationSessionUpdate(
                status=status
            )
            conversation_session_service.update_session(self.db, conversation_id, session_update)

            # Also store in context
            session = conversation_session_service.get_session(self.db, conversation_id)
            if session:
                session_context = session.context or {}
                session_context["status_history"] = session_context.get("status_history", [])
                session_context["status_history"].append({
                    "status": status,
                    "reason": resolved_reason,
                    "timestamp": datetime.now().isoformat()
                })
                conversation_session_service.update_session_context(
                    self.db, conversation_id, session_context
                )

            print(f"✓ Set conversation status to: {status}")

            return {
                "output": f"Status set to {status}",
                "status": status,
                "reason": resolved_reason
            }
        except Exception as e:
            print(f"✗ Error setting status: {e}")
            return {"error": f"Failed to set status: {e}"}

    async def _execute_question_classifier_node(self, node_data: dict, context: dict, results: dict, company_id: int):
        """
        Classifies user question into predefined classes using LLM.
        Returns the class name to determine which edge to follow.
        """
        model = node_data.get("model", "groq/llama-3.1-8b-instant")
        classes = node_data.get("classes", [])  # [{name: "billing", description: "..."}, ...]
        input_variable = node_data.get("input_variable", "user_message")
        output_variable = node_data.get("output_variable", "classification")

        # Get the question to classify from context
        question = context.get(input_variable, "")

        if not question:
            print(f"✗ Question classifier: No input found in '{input_variable}'")
            return {"output": "default", "classification": None}

        if not classes:
            print(f"✗ Question classifier: No classes configured")
            return {"output": "default", "classification": None}

        # Build classification prompt
        class_names = [cls["name"] for cls in classes]
        class_descriptions = "\n".join([
            f"- {cls['name']}: {cls.get('description', 'No description provided')}"
            for cls in classes
        ])

        prompt = f"""Classify the following question into exactly one of these categories:

{class_descriptions}

Question: "{question}"

Instructions:
- Respond with ONLY the category name, nothing else
- Choose the most relevant category
- If no category fits well, respond with "default"

Category:"""

        print(f"✓ Question classifier: Classifying '{question[:50]}...' into classes: {class_names}")

        try:
            # Call LLM using existing llm_tool_service
            llm_response = await self.llm_tool_service.execute(
                model=model,
                system_prompt="You are a classification assistant. Your only job is to classify questions into predefined categories. Always respond with just the category name, nothing else.",
                user_prompt=prompt,
                company_id=company_id
            )

            # Extract classification from response
            if isinstance(llm_response, dict):
                classification = llm_response.get("content", "").strip()
            else:
                classification = str(llm_response).strip()

            # Normalize and match to configured class
            classification_lower = classification.lower().strip()
            class_names_lower = [cls["name"].lower() for cls in classes]

            matched_class = None
            for cls in classes:
                if cls["name"].lower() == classification_lower:
                    matched_class = cls["name"]
                    break

            if matched_class:
                print(f"✓ Question classifier: Classified as '{matched_class}'")
                context[output_variable] = matched_class
                return {"output": matched_class, "classification": matched_class}
            else:
                print(f"ℹ Question classifier: LLM returned '{classification}' which doesn't match any class, using default")
                context[output_variable] = "default"
                return {"output": "default", "classification": None}

        except Exception as e:
            print(f"✗ Question classifier error: {e}")
            return {"output": "default", "classification": None, "error": str(e)}

    async def _execute_extract_entities_node(self, node_data: dict, context: dict, results: dict, company_id: int, workflow: Workflow, conversation_id: str):
        """
        Extracts entities from text using LLM.
        If extraction fails, pauses workflow to prompt user for missing entities.
        """
        entities_config = node_data.get("entities", [])
        input_source = node_data.get("input_source", "{{context.user_message}}")
        model = node_data.get("model", "groq/llama-3.1-8b-instant")
        retry_prompt_template = node_data.get("retry_prompt_template", "I couldn't find your {entity_description}. Please provide it.")
        max_retries = node_data.get("max_retries", 2)

        if not entities_config:
            print("✗ Extract entities: No entities configured")
            return {"output": {}, "status": "complete"}

        # Check if resuming from pause (user providing missing entity)
        # First, check for stale markers - if variable_to_save doesn't match, we have stale data
        extracting_entity_name = context.get("_extracting_entity_name")
        variable_to_save = context.get("variable_to_save", "")

        is_valid_resume = (
            extracting_entity_name is not None and
            variable_to_save == extracting_entity_name
        )

        if extracting_entity_name and not is_valid_resume:
            print(f"⚠ Extract entities: Stale resume markers detected (variable_to_save='{variable_to_save}' != extracting_entity_name='{extracting_entity_name}'). Starting fresh extraction.")
            # Clear stale markers and entity values
            context.pop("_extracting_entity_name", None)
            context.pop("_missing_entities", None)
            context.pop("_extraction_attempts", None)
            for entity_config in entities_config:
                entity_name = entity_config["name"]
                context.pop(entity_name, None)

        if is_valid_resume:
            missing_entities = context.get("_missing_entities", [])
            extraction_attempts = context.get("_extraction_attempts", {})

            # Deserialize missing_entities if it's a JSON string
            if isinstance(missing_entities, str):
                try:
                    missing_entities = json.loads(missing_entities)
                except (json.JSONDecodeError, TypeError):
                    missing_entities = []

            print(f"✓ Extract entities: Resuming, user provided value for '{extracting_entity_name}'")

            # Get the user's response - try extracting_entity_name first, then fall back to user_message
            user_provided_text = context.get(extracting_entity_name, "") or context.get("user_message", "")

            is_valid = False
            validation_error = None

            if user_provided_text:
                # Find the entity config for this entity
                entity_config = next((e for e in entities_config if e["name"] == extracting_entity_name), None)

                if entity_config:
                    # Use LLM to extract just the value from user's response
                    entity_description = entity_config.get("description", extracting_entity_name)
                    entity_type = entity_config.get("type", "text")

                    extraction_prompt = f"""Extract only the {entity_description} from this message.
Return ONLY the extracted value, nothing else.

Entity to extract: {extracting_entity_name} ({entity_type})
Description: {entity_description}
Message: "{user_provided_text}"

Extracted value:"""

                    try:
                        llm_response = await self.llm_tool_service.execute(
                            model=model,
                            system_prompt="You are an entity extraction assistant. Extract only the requested value from the message. Return ONLY the value itself, nothing else.",
                            chat_history=[],
                            user_prompt=extraction_prompt,
                            tools=[],
                            knowledge_base_id=None,
                            company_id=company_id
                        )

                        if isinstance(llm_response, dict):
                            extracted_value = llm_response.get("content", "").strip()
                        else:
                            extracted_value = str(llm_response).strip() if llm_response else user_provided_text

                        # Validate extracted value based on entity type
                        if extracted_value and extracted_value.lower() not in ['null', 'none', 'n/a']:
                            # Type-based validation
                            if entity_type == "number":
                                # Check if it's a valid number
                                try:
                                    float(extracted_value)
                                    is_valid = True
                                except ValueError:
                                    validation_error = f"'{extracted_value}' is not a valid number"
                            elif entity_type == "email":
                                # Basic email validation
                                import re
                                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                                if re.match(email_pattern, extracted_value):
                                    is_valid = True
                                else:
                                    validation_error = f"'{extracted_value}' is not a valid email"
                            elif entity_type == "phone":
                                # Basic phone validation (digits, spaces, +, -, ())
                                import re
                                phone_pattern = r'^[+]?[\d\s\-()]+$'
                                if re.match(phone_pattern, extracted_value) and len(extracted_value.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')) >= 10:
                                    is_valid = True
                                else:
                                    validation_error = f"'{extracted_value}' is not a valid phone number"
                            else:
                                # For text and other types, any non-empty value is valid
                                is_valid = True

                        # Save if valid, otherwise mark as still missing
                        if is_valid:
                            context[extracting_entity_name] = extracted_value
                            # Save to memory for persistence
                            memory_service.set_memory(
                                self.db,
                                MemoryCreate(key=extracting_entity_name, value=extracted_value),
                                agent_id=workflow.agent.id,
                                session_id=conversation_id
                            )
                            print(f"✓ Extracted and validated '{extracted_value}' for {extracting_entity_name} (type: {entity_type})")
                        else:
                            # Validation failed - don't save, keep in missing list
                            print(f"✗ Validation failed for {extracting_entity_name}: {validation_error}")

                    except Exception as e:
                        print(f"✗ LLM extraction failed for {extracting_entity_name}: {e}, using raw input")
                        context[extracting_entity_name] = user_provided_text
                        is_valid = True  # Exception path - accept raw input
                else:
                    # No config found, use raw input
                    context[extracting_entity_name] = user_provided_text
                    is_valid = True
            else:
                print(f"⚠ Warning: No user input found for '{extracting_entity_name}', using empty value")
                context[extracting_entity_name] = ""
                is_valid = True

            # Remove from missing list only if validation passed
            if is_valid and extracting_entity_name in missing_entities:
                missing_entities.remove(extracting_entity_name)

            # Clear the resumption markers
            del context["_extracting_entity_name"]

            # Check if there are more missing entities
            if missing_entities:
                # Ask for the next missing entity
                next_entity_name = missing_entities[0]
                entity_config = next((e for e in entities_config if e["name"] == next_entity_name), None)

                if entity_config:
                    entity_description = entity_config.get("description", next_entity_name)
                    entity_type_next = entity_config.get("type", "text")
                    prompt_text = retry_prompt_template.replace("{entity_description}", entity_description).replace("{entity_name}", next_entity_name)

                    # If this is the same entity that just failed validation, add the error message
                    if next_entity_name == extracting_entity_name and not is_valid and validation_error:
                        prompt_text = f"{validation_error}. {prompt_text}"

                    # Update context for next iteration
                    context["_extracting_entity_name"] = next_entity_name
                    context["_missing_entities"] = missing_entities
                    context["_extraction_attempts"] = extraction_attempts
                    context["variable_to_save"] = next_entity_name  # Standard pause/resume mechanism expects this

                    # Save to memory (for debugging and backup)
                    memory_service.set_memory(
                        self.db,
                        MemoryCreate(key="variable_to_save", value=next_entity_name),
                        agent_id=workflow.agent.id,
                        session_id=conversation_id
                    )
                    memory_service.set_memory(
                        self.db,
                        MemoryCreate(key="_extracting_entity_name", value=next_entity_name),
                        agent_id=workflow.agent.id,
                        session_id=conversation_id
                    )
                    memory_service.set_memory(
                        self.db,
                        MemoryCreate(key="_missing_entities", value=json.dumps(missing_entities)),
                        agent_id=workflow.agent.id,
                        session_id=conversation_id
                    )

                    print(f"ℹ Extract entities: Still missing {len(missing_entities)} entities, asking for '{next_entity_name}'")

                    return {
                        "status": "paused_for_prompt",
                        "prompt": {
                            "text": prompt_text,
                            "options": []
                        },
                        "output_variable": next_entity_name,
                        "re_execute_node": True  # Re-execute this node to continue collection
                    }

            # All entities collected, clean up context
            context.pop("_missing_entities", None)
            context.pop("_extraction_attempts", None)

            # Gather all extracted entities
            extracted_entities = {}
            for entity_config in entities_config:
                entity_name = entity_config["name"]
                extracted_entities[entity_name] = context.get(entity_name)

            print(f"✓ Extract entities: All entities collected: {list(extracted_entities.keys())}")
            return {"output": extracted_entities, "status": "complete"}

        # First time execution - attempt LLM extraction
        # Resolve input source placeholder
        input_text = self._resolve_placeholders(input_source, context, results)

        if not input_text:
            print(f"✗ Extract entities: No input text found from source '{input_source}'")
            input_text = ""

        # Build LLM extraction prompt
        entities_list = "\n".join([
            f"- {entity['name']}: {entity.get('description', 'No description')} (type: {entity.get('type', 'text')})"
            for entity in entities_config
        ])

        prompt = f"""Extract the following entities from the message.
Return a JSON object with entity names as keys.
If an entity is not found, use null as the value.

Entities to extract:
{entities_list}

Message: "{input_text}"

Return only valid JSON, nothing else:"""

        print(f"✓ Extract entities: Attempting to extract {len(entities_config)} entities from: '{input_text[:100]}...'")

        try:
            # Call LLM
            llm_response = await self.llm_tool_service.execute(
                model=model,
                system_prompt="You are an entity extraction assistant. Extract the requested entities from the message and return them in valid JSON format. Always return a JSON object with entity names as keys. Use null for entities that cannot be found.",
                chat_history=[],
                user_prompt=prompt,
                tools=[],  # Empty list instead of None
                knowledge_base_id=None,
                company_id=company_id
            )

            # Parse JSON response
            if isinstance(llm_response, dict):
                response_text = llm_response.get("content", "")
            else:
                response_text = str(llm_response) if llm_response else ""

            if not response_text:
                raise ValueError("LLM returned empty response")

            # Extract JSON from response (handle markdown code blocks)
            response_text = response_text.strip()
            if response_text.startswith("```json"):
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif response_text.startswith("```"):
                response_text = response_text.split("```")[1].split("```")[0].strip()

            extracted_entities = json.loads(response_text)

            # Validate that extracted_entities is a dict
            if not isinstance(extracted_entities, dict):
                raise ValueError(f"LLM returned non-dict response: {type(extracted_entities)}")

            print(f"✓ Extract entities: LLM returned: {extracted_entities}")

        except Exception as e:
            print(f"✗ Extract entities: LLM extraction failed: {e}")
            import traceback
            traceback.print_exc()
            # Treat all as missing
            extracted_entities = {entity["name"]: None for entity in (entities_config or [])}

        # Save extracted entities to context and check which are missing
        missing_entities = []
        for entity_config in entities_config:
            entity_name = entity_config["name"]
            entity_value = extracted_entities.get(entity_name)
            is_required = entity_config.get("required", True)

            if entity_value is not None and entity_value != "":
                # Validate extracted value based on entity type
                entity_type = entity_config.get("type", "text")
                is_valid = False
                validation_error = None

                if entity_type == "number":
                    try:
                        float(entity_value)
                        is_valid = True
                    except ValueError:
                        validation_error = f"'{entity_value}' is not a valid number"
                elif entity_type == "email":
                    import re
                    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                    if re.match(email_pattern, str(entity_value)):
                        is_valid = True
                    else:
                        validation_error = f"'{entity_value}' is not a valid email"
                elif entity_type == "phone":
                    import re
                    phone_pattern = r'^[+]?[\d\s\-()]+$'
                    entity_value_str = str(entity_value)
                    if re.match(phone_pattern, entity_value_str) and len(entity_value_str.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')) >= 10:
                        is_valid = True
                    else:
                        validation_error = f"'{entity_value}' is not a valid phone number"
                else:
                    # For text and other types, any non-empty value is valid
                    is_valid = True

                if is_valid:
                    # Successfully extracted and validated
                    context[entity_name] = entity_value
                    # Also save to memory to ensure persistence across pauses
                    memory_service.set_memory(
                        self.db,
                        MemoryCreate(key=entity_name, value=entity_value),
                        agent_id=workflow.agent.id,
                        session_id=conversation_id
                    )
                    print(f"✓ Entity '{entity_name}' extracted and validated: {entity_value} (type: {entity_type})")
                else:
                    # Validation failed - treat as missing
                    if is_required:
                        missing_entities.append(entity_name)
                        print(f"✗ Entity '{entity_name}' extracted but validation failed: {validation_error}")
                    else:
                        context[entity_name] = None
                        print(f"ℹ Entity '{entity_name}' validation failed but optional: {validation_error}")
            elif is_required:
                # Missing and required
                missing_entities.append(entity_name)
                print(f"✗ Entity '{entity_name}' missing and required")
            else:
                # Missing but optional
                context[entity_name] = None
                print(f"ℹ Entity '{entity_name}' missing but optional, setting to null")

        # If all required entities extracted, return success
        if not missing_entities:
            print(f"✓ Extract entities: All required entities extracted successfully")
            return {"output": extracted_entities, "status": "complete"}

        # Some entities missing - pause and ask for first one
        first_missing = missing_entities[0]
        entity_config = next((e for e in entities_config if e["name"] == first_missing), None)

        if entity_config:
            entity_description = entity_config.get("description", first_missing)
            prompt_text = retry_prompt_template.replace("{entity_description}", entity_description).replace("{entity_name}", first_missing)
        else:
            prompt_text = f"Please provide {first_missing}"

        # Save state to context for resume
        context["_missing_entities"] = missing_entities
        context["_extracting_entity_name"] = first_missing
        context["_extraction_attempts"] = {entity: 0 for entity in missing_entities}
        context["variable_to_save"] = first_missing  # Standard pause/resume mechanism expects this

        # Save to memory (for debugging and backup)
        memory_service.set_memory(
            self.db,
            MemoryCreate(key="variable_to_save", value=first_missing),
            agent_id=workflow.agent.id,
            session_id=conversation_id
        )
        memory_service.set_memory(
            self.db,
            MemoryCreate(key="_extracting_entity_name", value=first_missing),
            agent_id=workflow.agent.id,
            session_id=conversation_id
        )
        memory_service.set_memory(
            self.db,
            MemoryCreate(key="_missing_entities", value=json.dumps(missing_entities)),
            agent_id=workflow.agent.id,
            session_id=conversation_id
        )

        print(f"ℹ Extract entities: {len(missing_entities)} entities missing, asking for '{first_missing}'")

        return {
            "status": "paused_for_prompt",
            "prompt": {
                "text": prompt_text,
                "options": []
            },
            "output_variable": first_missing,
            "re_execute_node": True  # Re-execute this node to continue collection
        }

    # ============================================================
    # SUBWORKFLOW EXECUTION METHODS
    # ============================================================

    def _get_execution_chain(self, conversation_id: str) -> list:
        """Get list of workflow IDs currently in the execution chain (for circular reference detection)."""
        session = conversation_session_service.get_session(self.db, conversation_id)
        if not session or not session.subworkflow_stack:
            return []
        return [entry["workflow_id"] for entry in session.subworkflow_stack]

    def _detect_circular_reference(self, workflow_id: int, subworkflow_id: int, company_id: int, visited: set = None) -> bool:
        """
        Statically detect if calling subworkflow_id would create a cycle.
        Used for validation at save time and runtime.
        """
        if visited is None:
            visited = set()

        if subworkflow_id == workflow_id:
            return True
        if subworkflow_id in visited:
            return False  # Already checked this path

        visited.add(subworkflow_id)

        # Get the subworkflow and check its subworkflow nodes
        subworkflow = workflow_service.get_workflow(self.db, subworkflow_id, company_id)
        if not subworkflow or not subworkflow.visual_steps:
            return False

        visual_steps = subworkflow.visual_steps
        if isinstance(visual_steps, str):
            try:
                visual_steps = json.loads(visual_steps)
            except json.JSONDecodeError:
                return False

        nodes = visual_steps.get("nodes", [])
        for node in nodes:
            if node.get("type") == "subworkflow":
                nested_subworkflow_id = node.get("data", {}).get("subworkflow_id")
                if nested_subworkflow_id and self._detect_circular_reference(
                    workflow_id, nested_subworkflow_id, company_id, visited
                ):
                    return True

        return False

    async def _execute_subworkflow_node(
        self,
        node_data: dict,
        context: dict,
        results: dict,
        company_id: int,
        workflow: Workflow,
        conversation_id: str,
        current_depth: int = 0
    ):
        """
        Execute a subworkflow node by calling another workflow.

        Node data structure:
        {
            "subworkflow_id": int,      # ID of workflow to call
            "output_variable": str      # Variable name to store subworkflow results
        }
        """
        subworkflow_id = node_data.get("subworkflow_id")
        output_variable = node_data.get("output_variable", "subworkflow_result")

        if not subworkflow_id:
            return {"error": "No subworkflow selected. Please configure the subworkflow node."}

        # Depth check
        if current_depth >= settings.MAX_SUBWORKFLOW_DEPTH:
            return {
                "error": f"Maximum subworkflow depth ({settings.MAX_SUBWORKFLOW_DEPTH}) exceeded. Consider simplifying your workflow structure."
            }

        # Circular reference check at runtime
        execution_chain = self._get_execution_chain(conversation_id)
        if subworkflow_id in execution_chain:
            return {
                "error": f"Circular reference detected: workflow {subworkflow_id} is already in execution chain"
            }

        # Static circular reference check
        if self._detect_circular_reference(workflow.id, subworkflow_id, company_id):
            return {
                "error": f"Circular reference detected: subworkflow {subworkflow_id} would create a cycle"
            }

        # Fetch subworkflow
        subworkflow = workflow_service.get_workflow(self.db, subworkflow_id, company_id)
        if not subworkflow:
            return {"error": f"Subworkflow with ID {subworkflow_id} not found"}

        print(f"✓ Subworkflow node: Executing subworkflow '{subworkflow.name}' (ID: {subworkflow_id}) at depth {current_depth + 1}")

        # Return execution directive - actual execution happens in execute_workflow
        return {
            "status": "execute_subworkflow",
            "subworkflow_id": subworkflow_id,
            "subworkflow_name": subworkflow.name,
            "output_variable": output_variable,
            "depth": current_depth + 1
        }

    async def execute_workflow(self, user_message: str, company_id: int, workflow_id: int = None, workflow: Workflow = None, conversation_id: str = None, attachments: list = None, option_key: str = None):
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

        # Load all memories for this session into the context
        context = {memory.key: memory.value for memory in memory_service.get_all_memories(self.db, agent_id=workflow_obj.agent.id, session_id=conversation_id)}

        # ============================================================
        # WORKFLOW INTENT DETECTION
        # ============================================================
        # Check if this workflow has intent detection enabled
        if self.workflow_intent_service.workflow_has_intents_enabled(workflow_obj):
            print(f"DEBUG: Intent detection enabled for workflow '{workflow_obj.name}'")

            intent_match = await self.workflow_intent_service.detect_intent_for_workflow(
                message=user_message,
                workflow=workflow_obj,
                conversation_id=conversation_id,
                company_id=company_id
            )

            if intent_match:
                intent_dict, confidence, entities, matched_method = intent_match
                print(f"✓ Workflow intent detected: {intent_dict.get('name')} (confidence: {confidence:.2f}, method: {matched_method})")

                # Add detected intent information to context
                context['detected_intent'] = intent_dict.get('name')
                context['intent_confidence'] = confidence
                context['intent_matched_method'] = matched_method

                # Merge extracted entities into context
                if entities:
                    print(f"✓ Extracted entities: {entities}")
                    context.update(entities)

                    # Save entities to memory for persistence
                    for entity_name, entity_value in entities.items():
                        memory_service.set_memory(
                            self.db,
                            MemoryCreate(key=entity_name, value=entity_value),
                            agent_id=workflow_obj.agent.id,
                            session_id=conversation_id
                        )

                # Check if confidence meets auto-trigger threshold
                if not self.workflow_intent_service.should_auto_trigger(workflow_obj, confidence):
                    min_confidence = workflow_obj.intent_config.get("min_confidence", 0.7)
                    print(f"ℹ Intent confidence {confidence:.2f} below threshold {min_confidence}, workflow may not proceed")
                    # Continue execution anyway since workflow was explicitly called
            else:
                print(f"✗ No intent matched for workflow '{workflow_obj.name}'")

        results = {}

        # Ensure visual_steps is a dictionary
        visual_steps_data = workflow_obj.visual_steps

        # If this is a parent workflow with no visual_steps, try to use the active version instead
        if visual_steps_data is None and hasattr(workflow_obj, 'versions') and workflow_obj.versions:
            active_version = next((v for v in workflow_obj.versions if v.is_active), None)
            if active_version and active_version.visual_steps:
                print(f"DEBUG: Using active version {active_version.id} (v{active_version.version}) instead of parent {workflow_obj.id}")
                visual_steps_data = active_version.visual_steps

        # Handle None or empty visual_steps
        if visual_steps_data is None:
            print(f"WARNING: Workflow {workflow_obj.id} has no visual_steps defined")
            return {"status": "error", "response": "Workflow configuration is incomplete. Please contact support."}

        if isinstance(visual_steps_data, str):
            try:
                visual_steps_data = json.loads(visual_steps_data)
            except json.JSONDecodeError:
                return {"status": "error", "response": "Failed to parse workflow visual steps."}

        # Validate that visual_steps_data has required structure
        if not isinstance(visual_steps_data, dict):
            print(f"WARNING: Workflow {workflow_obj.id} visual_steps is not a dict: {type(visual_steps_data)}")
            return {"status": "error", "response": "Workflow configuration is invalid. Please contact support."}

        graph_engine = GraphExecutionEngine(visual_steps_data)
        
        print(f"DEBUG: Workflow resumed with user_message: '{user_message}'")
        # Check if workflow is paused (indicated by next_step_id being set)
        should_resume = False
        if session.next_step_id:
            current_node_id = session.next_step_id

            # Check if the node exists in the current workflow version
            # This can fail if the workflow version was changed while session was paused
            if current_node_id not in graph_engine.nodes:
                print(f"WARNING: Paused node '{current_node_id}' not found in current workflow version. Restarting workflow.")
                # Reset session state and start fresh
                session_update = ConversationSessionUpdate(
                    next_step_id=None,
                    context={}
                )
                conversation_session_service.update_session(self.db, conversation_id, session_update)
                # Clear memories for clean restart
                memory_service.delete_all_memories(self.db, agent_id=workflow_obj.agent.id, session_id=conversation_id)
                # Start from beginning
                current_node_id = graph_engine.find_start_node()
                context = {"initial_user_message": user_message, "user_attachments": attachments or []}
                memory_service.set_memory(self.db, MemoryCreate(key="initial_user_message", value=user_message), agent_id=workflow_obj.agent.id, session_id=conversation_id)
            else:
                should_resume = True
                print(f"DEBUG: Resuming from paused state. Context from memory: {context}")
                # Add attachments to context when resuming
                context["user_attachments"] = attachments or []
                # The variable to save was stored in the context before pausing.
                variable_to_save = context.get("variable_to_save")
                print(f"DEBUG: Retrieved variable_to_save: '{variable_to_save}'")
                if variable_to_save:
                    # Determine what value to save to the workflow variable
                    # If option_key is provided (user selected a prompt option), use the key
                    # Otherwise, use the display message (user_message)
                    value_to_save = option_key if option_key else user_message
                    print(f"DEBUG: Will save to variable '{variable_to_save}': option_key={option_key}, user_message={user_message}, value_to_save={value_to_save}")

                    # Check if the incoming message is a JSON string (from a form submission)
                    try:
                        form_data = json.loads(value_to_save)
                        context[variable_to_save] = form_data
                    except (json.JSONDecodeError, TypeError):
                        # It's a plain text response (e.g., from a prompt)
                        # If there are attachments, save them along with the message
                        if attachments:
                            context[variable_to_save] = {
                                "text": value_to_save,
                                "attachments": attachments
                            }
                            print(f"DEBUG: Saved message with {len(attachments)} attachment(s) to '{variable_to_save}'")
                        else:
                            context[variable_to_save] = value_to_save
                    print(f"DEBUG: Context after updating with user message: {context}")
                    # Save the updated context back to memory
                    memory_service.set_memory(self.db, MemoryCreate(key=variable_to_save, value=context[variable_to_save]), agent_id=workflow_obj.agent.id, session_id=conversation_id)
        else:
            current_node_id = graph_engine.find_start_node()
            # For the very first message in a workflow
            context["initial_user_message"] = user_message
            context["user_attachments"] = attachments or []
            memory_service.set_memory(self.db, MemoryCreate(key="initial_user_message", value=user_message), agent_id=workflow_obj.agent.id, session_id=conversation_id)

        last_executed_node_id = None
        response_messages = []  # Collect all response node outputs
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
                # Support multiple keys for backwards compatibility: tool_name, tool, name
                tool_name = node_data.get("tool_name") or node_data.get("tool") or node_data.get("name")
                if not tool_name:
                    result = {"error": f"Tool node '{current_node_id}' has no tool configured. Please select a tool in the properties panel."}
                else:
                    raw_params = node_data.get("parameters", {}) or node_data.get("params", {})
                    resolved_params = {k: self._resolve_placeholders(v, context, results) for k, v in raw_params.items()}
                    result = await self._execute_tool(tool_name, resolved_params, company_id=workflow.agent.company_id, session_id=conversation_id)

            elif node_type == "http_request":
                result = await self._execute_http_request_node(node_data, context, results)

            elif node_type == "llm":
                result = await self._execute_llm_node(node_data, context, results, company_id=workflow.agent.company_id, workflow=workflow, conversation_id=conversation_id)

            elif node_type == "data_manipulation":
                result = await self._execute_data_manipulation_node(node_data, context, results)

            elif node_type == "code":
                result = await self._execute_code_node(node_data, context, results)

            elif node_type == "knowledge":
                result = await self._execute_knowledge_retrieval_node(node_data, context, results, company_id=workflow_obj.agent.company_id, workflow=workflow_obj)

            elif node_type == "condition":
                result = self._execute_conditional_node(node_data, context, results)

            elif node_type == "listen":
                params = node_data.get("params", {})
                expected_input_type = params.get("expected_input_type", "any")
                result = {
                    "status": "paused_for_input",
                    "expected_input_type": expected_input_type
                }

            elif node_type == "prompt":
                params = node_data.get("params", {})
                options_mode = params.get("options_mode", "manual")
                options_list = []

                if options_mode == "variable":
                    # Resolve variable reference
                    options_variable = params.get("options_variable", "")
                    if options_variable:
                        resolved_options = self._resolve_placeholders(options_variable, context, results)
                        # If resolved value is a string (JSON), parse it
                        if isinstance(resolved_options, str):
                            try:
                                resolved_options = json.loads(resolved_options)
                            except json.JSONDecodeError:
                                resolved_options = []
                        # Handle dictionary - convert to list of {key, value} pairs
                        if isinstance(resolved_options, dict):
                            options_list = [
                                {"key": str(k), "value": str(v)}
                                for k, v in resolved_options.items()
                            ]
                        # Ensure it's a list of key-value dicts
                        elif isinstance(resolved_options, list):
                            options_list = [
                                opt if isinstance(opt, dict) and 'key' in opt and 'value' in opt
                                else {"key": str(opt), "value": str(opt)}
                                for opt in resolved_options
                            ]
                else:
                    # Manual mode: use options array directly
                    options = params.get("options", [])
                    if isinstance(options, str):
                        # Backward compatibility: comma-separated string
                        options_list = [
                            {"key": opt.strip(), "value": opt.strip()}
                            for opt in options.split(',') if opt.strip()
                        ]
                    elif isinstance(options, list):
                        options_list = [
                            opt if isinstance(opt, dict) and 'key' in opt and 'value' in opt
                            else {"key": str(opt), "value": str(opt)}
                            for opt in options
                        ]

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

            elif node_type == "response":
                output_value = node_data.get("output_value", "")
                resolved_output = self._resolve_placeholders(output_value, context, results)
                result = {"output": resolved_output}
                # Broadcast intermediate response messages immediately
                if resolved_output:
                    response_messages.append(resolved_output)
                    # Check if there's a next node - if so, broadcast this as intermediate message
                    next_check = graph_engine.get_next_node(current_node_id, result)
                    if next_check:  # There's more nodes after this response
                        # Import here to avoid circular import
                        from app.api.v1.endpoints.websocket_conversations import manager as ws_manager
                        from app.services import chat_service
                        from app.schemas import chat_message as schemas_chat_message

                        # Save to database and broadcast properly formatted message
                        # Handle dict output (e.g., from Listen node with attachments)
                        message_text = resolved_output
                        if isinstance(resolved_output, dict):
                            message_text = resolved_output.get("text", str(resolved_output))
                        agent_message = schemas_chat_message.ChatMessageCreate(message=message_text, message_type="message")
                        db_agent_message = chat_service.create_chat_message(
                            self.db, agent_message,
                            workflow_obj.agent.id, conversation_id,
                            workflow_obj.agent.company_id, "agent",
                            assignee_id=None
                        )
                        await ws_manager.broadcast_to_session(
                            str(conversation_id),
                            schemas_chat_message.ChatMessage.model_validate(db_agent_message).model_dump_json(),
                            "agent"
                        )

                        # Generate TTS for chat_and_voice mode (intermediate response)
                        try:
                            from app.services import widget_settings_service, credential_service
                            from app.services.tts_service import TTSService
                            widget_settings = widget_settings_service.get_widget_settings(self.db, workflow_obj.agent.id)
                            if widget_settings and widget_settings.communication_mode == 'chat_and_voice':
                                tts_provider = workflow_obj.agent.tts_provider or 'voice_engine'
                                voice_id = workflow_obj.agent.voice_id or 'default'
                                openai_api_key = None
                                openai_credential = credential_service.get_credential_by_service_name(self.db, 'openai', workflow_obj.agent.company_id)
                                if openai_credential:
                                    try:
                                        openai_api_key = credential_service.get_decrypted_credential(self.db, openai_credential.id, workflow_obj.agent.company_id)
                                    except Exception:
                                        pass
                                tts_service = TTSService(openai_api_key=openai_api_key)
                                # Use message_text (already extracted from dict if needed)
                                audio_stream = tts_service.text_to_speech_stream(message_text, voice_id, tts_provider)
                                async for audio_chunk in audio_stream:
                                    await ws_manager.broadcast_bytes_to_session(str(conversation_id), audio_chunk)
                                await tts_service.close()
                                # Send audio_end marker so frontend knows this TTS is complete
                                await ws_manager.broadcast_to_session(
                                    str(conversation_id),
                                    json.dumps({"type": "audio_end"}),
                                    "agent"
                                )
                                print(f"[workflow_execution] TTS audio sent for intermediate response in session: {conversation_id}")
                        except Exception as tts_error:
                            print(f"[workflow_execution] TTS error for intermediate response: {tts_error}")

            # ============================================================
            # NEW CHAT-SPECIFIC NODES
            # ============================================================

            elif node_type == "intent_router":
                # Routes based on detected intent in context
                result = self._execute_intent_router_node(node_data, context, results)

            elif node_type == "entity_collector":
                # Collects required entities from user
                result = await self._execute_entity_collector_node(
                    node_data, context, results, workflow_obj, conversation_id
                )

            elif node_type == "check_entity":
                # Checks if entity exists in context
                result = self._execute_check_entity_node(node_data, context, results)

            elif node_type == "update_context":
                # Updates context variables
                result = self._execute_update_context_node(node_data, context, results)

            elif node_type == "tag_conversation":
                # Adds tags to conversation
                result = self._execute_tag_conversation_node(
                    node_data, context, results, conversation_id
                )

            elif node_type == "assign_to_agent":
                # Transfers conversation to human agent
                result = self._execute_assign_to_agent_node(
                    node_data, context, results, conversation_id, workflow_obj.agent.company_id
                )

            elif node_type == "set_status":
                # Sets conversation status
                result = self._execute_set_status_node(
                    node_data, context, results, conversation_id
                )

            elif node_type == "question_classifier":
                # Classifies question using LLM and routes accordingly
                result = await self._execute_question_classifier_node(
                    node_data, context, results, workflow_obj.agent.company_id
                )

            elif node_type == "extract_entities":
                # Extracts entities from message using LLM
                result = await self._execute_extract_entities_node(
                    node_data, context, results, workflow_obj.agent.company_id, workflow_obj, conversation_id
                )

            elif node_type == "subworkflow":
                # Execute another workflow as a subworkflow
                # Get current depth from session's subworkflow_stack
                current_depth = len(session.subworkflow_stack or [])
                result = await self._execute_subworkflow_node(
                    node_data, context, results, company_id, workflow_obj, conversation_id, current_depth
                )

            results[current_node_id] = result
            last_executed_node_id = current_node_id

            if result and result.get("status") in ["paused_for_input", "paused_for_prompt", "paused_for_form"]:
                # Check if this node wants to re-execute itself (for multi-step collection)
                # If result has 're_execute_node', save current node as next_step_id instead
                if result.get("re_execute_node"):
                    next_node_id = current_node_id  # Re-execute this node
                else:
                    next_node_id = graph_engine.get_next_node(current_node_id, result)

                # Before pausing, save the variable name that should receive the input.
                # First check if the result provides output_variable (for dynamic nodes like extract_entities)
                # Otherwise check the node's configuration data
                variable_to_save = result.get("output_variable")
                if not variable_to_save:
                    variable_to_save = node_data.get("output_variable")
                    if not variable_to_save:
                        params = node_data.get("params", {})
                        # Check both 'output_variable' and 'save_to_variable' for backward compatibility
                        variable_to_save = params.get("output_variable") or params.get("save_to_variable")
                
                print(f"DEBUG: Pausing node data: {node_data}")
                print(f"DEBUG: 'output_variable' from node data is: '{variable_to_save}'")
                if variable_to_save:
                    context["variable_to_save"] = variable_to_save
                    memory_service.set_memory(self.db, MemoryCreate(key="variable_to_save", value=variable_to_save), agent_id=workflow_obj.agent.id, session_id=conversation_id)

                # Keep session status as 'active' so it remains visible in the UI
                # The presence of next_step_id indicates the workflow is paused waiting for input
                session_update = ConversationSessionUpdate(
                    next_step_id=next_node_id,
                    context=context,
                    status='active'  # Keep as active instead of paused to keep conversation visible
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
                if "expected_input_type" in result:
                    response_payload["expected_input_type"] = result["expected_input_type"]

                # Include last response message for TTS in voice mode
                if response_messages:
                    response_payload["response"] = response_messages[-1]

                return response_payload

            # Handle subworkflow execution
            if result and result.get("status") == "execute_subworkflow":
                subworkflow_id = result["subworkflow_id"]
                output_variable = result["output_variable"]
                depth = result["depth"]

                # Push current state to subworkflow stack
                subworkflow_stack = list(session.subworkflow_stack or [])
                subworkflow_entry = {
                    "workflow_id": subworkflow_id,
                    "parent_node_id": current_node_id,
                    "parent_workflow_id": workflow_obj.id,
                    "parent_next_step_id": graph_engine.get_next_node(current_node_id, {"output": "subworkflow_complete"}),
                    "output_variable": output_variable,
                    "depth": depth
                }
                subworkflow_stack.append(subworkflow_entry)

                # Update session with stack and switch to subworkflow
                session_update = ConversationSessionUpdate(
                    subworkflow_stack=subworkflow_stack,
                    workflow_id=subworkflow_id,
                    next_step_id=None,  # Start from beginning of subworkflow
                    context=context
                )
                conversation_session_service.update_session(self.db, conversation_id, session_update)
                self.db.refresh(session)

                print(f"✓ Subworkflow: Pushed to stack, entering subworkflow {subworkflow_id} at depth {depth}")

                # Recursively execute subworkflow
                return await self.execute_workflow(
                    user_message=user_message,
                    company_id=company_id,
                    workflow_id=subworkflow_id,
                    conversation_id=conversation_id,
                    attachments=attachments
                )

            if result and "error" in result:
                # The get_next_node method will handle routing to the error path if it exists
                pass

            print(f"DEBUG: About to call get_next_node for node '{current_node_id}' with result: {result}")
            current_node_id = graph_engine.get_next_node(current_node_id, result)
            print(f"DEBUG: get_next_node returned: {current_node_id}")

        # Get the final output before checking for subworkflow completion
        if response_messages:
            final_output = response_messages[-1]
        else:
            final_output = results.get(last_executed_node_id, {}).get("output", "Workflow completed.")

        # ============================================================
        # SUBWORKFLOW COMPLETION - Check if we need to return to parent
        # ============================================================
        subworkflow_stack = list(session.subworkflow_stack or [])
        if subworkflow_stack:
            # This workflow was a subworkflow - pop stack and continue parent
            completed_entry = subworkflow_stack.pop()
            output_variable = completed_entry["output_variable"]
            parent_workflow_id = completed_entry["parent_workflow_id"]
            parent_next_step_id = completed_entry["parent_next_step_id"]

            print(f"✓ Subworkflow completed: Returning to parent workflow {parent_workflow_id}, next step: {parent_next_step_id}")

            # Store subworkflow results in context under the configured output variable
            context[output_variable] = {
                "output": final_output,
                "results": {k: v.get("output") for k, v in results.items() if isinstance(v, dict) and "output" in v}
            }

            # Update session to return to parent workflow
            session_update = ConversationSessionUpdate(
                subworkflow_stack=subworkflow_stack if subworkflow_stack else None,
                workflow_id=parent_workflow_id,
                next_step_id=parent_next_step_id,
                context=context
            )
            conversation_session_service.update_session(self.db, conversation_id, session_update)
            self.db.refresh(session)

            # Continue parent workflow from where it left off
            # Pass empty user_message since we're continuing, not responding to new input
            return await self.execute_workflow(
                user_message="",
                company_id=company_id,
                workflow_id=parent_workflow_id,
                conversation_id=conversation_id,
                attachments=None
            )

        # Finalizing the workflow (only if not a subworkflow)
        # Instead of marking the session as 'completed', keep it 'active' so multiple workflows can run
        # and the conversation remains visible. Track workflow completion in context.
        context['last_workflow_completed_at'] = datetime.now().isoformat()
        context['last_workflow_id'] = workflow_obj.id

        # Clean up any extraction-related markers from context and memory so they don't interfere with future runs
        extraction_markers = ['_extracting_entity_name', '_missing_entities', '_extraction_attempts', 'variable_to_save']
        for marker in extraction_markers:
            context.pop(marker, None)
            # Also delete from memory service
            try:
                if workflow_obj.agent:
                    memory_service.delete_memory(self.db, marker, workflow_obj.agent.id, conversation_id)
            except:
                pass  # Marker might not exist in memory
        print(f"DEBUG: Cleaned up extraction markers from context and memory on workflow completion")

        # Update session context
        session_update = ConversationSessionUpdate(status='active', context=context, subworkflow_stack=None)
        conversation_session_service.update_session(self.db, conversation_id, session_update)

        # Clear workflow_id and next_step_id directly so next message triggers fresh workflow search
        session.workflow_id = None
        session.next_step_id = None
        self.db.commit()
        self.db.refresh(session)
        print(f"DEBUG: Workflow completed. Cleared workflow_id and next_step_id for session {conversation_id}")

        # Clear all memory for this session so next workflow starts fresh
        if workflow_obj.agent:
            memory_service.delete_all_memories(self.db, agent_id=workflow_obj.agent.id, session_id=conversation_id)
            print(f"DEBUG: Cleared all memory for session {conversation_id}")

        return {"status": "completed", "response": final_output, "conversation_id": conversation_id}