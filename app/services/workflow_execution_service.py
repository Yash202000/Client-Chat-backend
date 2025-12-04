import json
import re
import uuid
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

        def replace_func(match):
            placeholder = match.group(1).strip()
            print(f"  - Found placeholder: {placeholder}")
            path = placeholder.split(".")
            source = path[0]

            resolved_value = ''
            if source == "context":
                # Support nested paths like context.customer_data.reason
                remaining_path = path[1:]  # ['customer_data', 'reason']
                resolved_value = drill_down(context, remaining_path)
                print(f"    - Source: context, Path: {remaining_path}, Value: '{resolved_value}'")
            else:
                # Handle results from previous nodes
                step_result = results.get(source)
                print(f"    - Source: results, Step: {source}, Result: {step_result}")
                if step_result:
                    # Start with the step result and drill down
                    remaining_path = path[1:]  # e.g., ['output'] or ['output', 'content']
                    resolved_value = drill_down(step_result, remaining_path) if remaining_path else step_result

                    # If no specific path given, try to get the output
                    if not remaining_path:
                        output_value = step_result.get("output")
                        if isinstance(output_value, dict):
                            resolved_value = output_value.get("content", '')
                        elif output_value is None:
                            resolved_value = ''
                        else:
                            resolved_value = output_value
                print(f"    - Resolved value: '{resolved_value}'")

            return str(resolved_value) if resolved_value is not None else ''

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

        # Use asyncio to run the async HTTP request
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def make_request():
            async with httpx.AsyncClient(timeout=settings.HTTP_REQUEST_TIMEOUT) as client:
                try:
                    response = None
                    if method == "GET":
                        response = await client.get(resolved_url, headers=headers)
                    elif method == "POST":
                        response = await client.post(resolved_url, headers=headers, json=body)
                    elif method == "PUT":
                        response = await client.put(resolved_url, headers=headers, json=body)
                    elif method == "DELETE":
                        response = await client.delete(resolved_url, headers=headers)
                    else:
                        return {"error": f"Unsupported HTTP method: {method}"}

                    response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
                    content_type = response.headers.get('Content-Type', '')
                    if 'application/json' in content_type:
                        return {"output": response.json()}
                    else:
                        return {"output": response.text}
                except httpx.HTTPError as e:
                    return {"error": f"HTTP request failed: {e}"}
                except Exception as e:
                    return {"error": f"Error executing HTTP request: {e}"}

        try:
            return loop.run_until_complete(make_request())
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
                # Disable AI for manual handling
                session_update = ConversationSessionUpdate(
                    is_ai_enabled=False,
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

    async def execute_workflow(self, user_message: str, company_id: int, workflow_id: int = None, workflow: Workflow = None, conversation_id: str = None):
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
        if session.next_step_id:
            current_node_id = session.next_step_id
            print(f"DEBUG: Resuming from paused state. Context from memory: {context}")
            # The variable to save was stored in the context before pausing.
            variable_to_save = context.get("variable_to_save")
            print(f"DEBUG: Retrieved variable_to_save: '{variable_to_save}'")
            if variable_to_save:
                # Check if the incoming message is a JSON string (from a form submission)
                try:
                    form_data = json.loads(user_message)
                    context[variable_to_save] = form_data
                except (json.JSONDecodeError, TypeError):
                     # It's a plain text response (e.g., from a prompt)
                    context[variable_to_save] = user_message
                print(f"DEBUG: Context after updating with user message: {context}")
                # Save the updated context back to memory
                memory_service.set_memory(self.db, MemoryCreate(key=variable_to_save, value=context[variable_to_save]), agent_id=workflow_obj.agent.id, session_id=conversation_id)
        else:
            current_node_id = graph_engine.find_start_node()
            # For the very first message in a workflow
            context["initial_user_message"] = user_message
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
                        agent_message = schemas_chat_message.ChatMessageCreate(message=resolved_output, message_type="message")
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

            results[current_node_id] = result
            last_executed_node_id = current_node_id

            if result and result.get("status") in ["paused_for_input", "paused_for_prompt", "paused_for_form"]:
                next_node_id = graph_engine.get_next_node(current_node_id, result)
                
                # Before pausing, save the variable name that should receive the input.
                # This information should be part of the node's data.
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
                
                return response_payload

            if result and "error" in result:
                # The get_next_node method will handle routing to the error path if it exists
                pass

            print(f"DEBUG: About to call get_next_node for node '{current_node_id}' with result: {result}")
            current_node_id = graph_engine.get_next_node(current_node_id, result)
            print(f"DEBUG: get_next_node returned: {current_node_id}")

        # Finalizing the workflow
        # Instead of marking the session as 'completed', keep it 'active' so multiple workflows can run
        # and the conversation remains visible. Track workflow completion in context.
        context['last_workflow_completed_at'] = datetime.now().isoformat()
        context['last_workflow_id'] = workflow_obj.id

        # Update session context
        session_update = ConversationSessionUpdate(status='active', context=context)
        conversation_session_service.update_session(self.db, conversation_id, session_update)

        # Clear workflow_id and next_step_id directly so next message triggers fresh workflow search
        session.workflow_id = None
        session.next_step_id = None
        self.db.commit()
        self.db.refresh(session)
        print(f"DEBUG: Workflow completed. Cleared workflow_id and next_step_id for session {conversation_id}")

        # Return only the last response message (intermediate ones were already broadcasted)
        if response_messages:
            final_output = response_messages[-1]  # Last message only
        else:
            final_output = results.get(last_executed_node_id, {}).get("output", "Workflow completed.")

        return {"status": "completed", "response": final_output, "conversation_id": conversation_id}