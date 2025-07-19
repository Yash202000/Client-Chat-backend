import json
import re
import uuid
from sqlalchemy.orm import Session
from app.models.workflow import Workflow
from app.models.tool import Tool
from app.services import tool_service, conversation_session_service
from app.schemas.conversation_session import ConversationSessionUpdate
from app.services.llm_tool_service import LLMToolService

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
        def replace_func(match):
            path = match.group(1).strip().split(".")
            source = path[0]
            key = path[1]
            if source == "context":
                return str(context.get(key, ''))
            elif key == "output":
                return str(results.get(source, {}).get("output", ''))
            return match.group(0)
        
        if isinstance(value, str):
            return re.sub(r"\{\{(.*?)\}\}", replace_func, value)
        return value

    def execute_workflow(self, workflow: Workflow, user_message: str, conversation_id: str = None):
        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        session = conversation_session_service.get_or_create_session(
            self.db, conversation_id, workflow.id
        )

        context = session.context or {}
        results = {}
        
        # If resuming, the user's message might need to be saved to a variable
        if session.status == 'paused' and session.next_step_id:
            # The 'listen' node should have defined where to save the input
            # We find the listen node that pointed to this next_step_id
            workflow_steps = workflow.steps.get("steps", {})
            listen_step_id = None
            listen_step_config = None
            for step_id, step_config in workflow_steps.items():
                if step_config.get("next_step_on_success") == session.next_step_id:
                    listen_step_id = step_id
                    listen_step_config = step_config
                    break
            
            if listen_step_config:
                output_variable = listen_step_config.get("params", {}).get("save_to_variable")
                if output_variable:
                    context[output_variable] = user_message

        current_step_name = session.next_step_id or workflow.steps.get("first_step")
        if not current_step_name:
            # Fallback for older workflows or if first_step is missing
            workflow_steps = workflow.steps.get("steps", {})
            if workflow_steps:
                current_step_name = next(iter(workflow_steps))
            else:
                return {"error": "Workflow has no steps."}

        while current_step_name:
            workflow_steps = workflow.steps.get("steps", {})
            step = workflow_steps.get(current_step_name)
            if not step:
                break

            tool_name = step.get("tool")
            raw_params = step.get("params", {})

            # Resolve parameters using context and previous step results
            resolved_params = {k: self._resolve_placeholders(v, context, results) for k, v in raw_params.items()}

            tool_result = self._execute_tool(tool_name, resolved_params, company_id=workflow.agent.company_id)
            results[current_step_name] = tool_result

            if tool_result.get("status") in ["paused_for_input", "paused_for_prompt"]:
                # Workflow is pausing, save state and exit
                session_update = ConversationSessionUpdate(
                    next_step_id=step.get("next_step_on_success"),
                    context=context,
                    status='paused'
                )
                conversation_session_service.update_session(self.db, conversation_id, session_update)
                
                # Return a rich object to the caller
                response_payload = {
                    "status": tool_result.get("status"),
                    "conversation_id": conversation_id
                }
                if "prompt" in tool_result:
                    response_payload["prompt"] = tool_result["prompt"]
                
                return response_payload

            if "error" in tool_result:
                current_step_name = step.get("next_step_on_failure")
            else:
                current_step_name = step.get("next_step_on_success")

        # Workflow finished, update session to completed
        session_update = ConversationSessionUpdate(status='completed', context=context)
        conversation_session_service.update_session(self.db, conversation_id, session_update)

        final_output = results.get(list(results.keys())[-1], {}).get("output", "Workflow completed.")
        return {"status": "completed", "response": final_output, "conversation_id": conversation_id}
