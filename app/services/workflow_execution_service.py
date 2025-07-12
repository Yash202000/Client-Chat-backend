from sqlalchemy.orm import Session
from app.models.workflow import Workflow
from app.models.tool import Tool
from app.services import tool_service
import json
import re

class WorkflowExecutionService:
    def __init__(self, db: Session):
        self.db = db

    def _execute_tool(self, tool_name: str, params: dict):
        tool = self.db.query(Tool).filter(Tool.name == tool_name).first()
        if not tool:
            return {"error": f"Tool '{tool_name}' not found."}

        try:
            # Prepare the execution environment
            exec_globals = {"args": params, "result": None}
            # Execute the tool code
            exec(tool.code, exec_globals)
            return {"output": exec_globals["result"]}
        except Exception as e:
            return {"error": f"Error executing tool {tool_name}: {e}"}

    def execute_workflow(self, workflow: Workflow, initial_context: dict = None):
        if not workflow or not workflow.steps:
            return {"error": "Invalid workflow or no steps defined."}
        context = initial_context if initial_context is not None else {}
        results = {}
        current_step_name = "step1" # Assuming the first step is always named 'step1'
        last_successful_step_name = None # Track the last successful step

        workflow_steps = workflow.steps.get("steps", {}) # Access the nested 'steps' dictionary

        def replace_placeholder(match):
            path = match.group(1).strip().split(".")
            if len(path) == 2 and path[0] == "context":
                context_key = path[1]
                # Attempt to retrieve the value from context and preserve its type
                value_from_context = context.get(context_key)
                if value_from_context is not None:
                    return value_from_context # Return the original type
                return match.group(0) # Return original if not found in context
            elif len(path) == 2 and path[1] == "output":
                prev_step_name = path[0]
                return str(results.get(prev_step_name, {}).get("output", ""))
            return match.group(0) # Return original if not a valid reference

        while current_step_name:
            step = workflow_steps.get(current_step_name)
            if not step:
                break

            tool_name = step.get("tool")
            params = step.get("params", {})

            # Resolve parameters from previous step outputs
            resolved_params = {}
            for key, value in params.items():
                if isinstance(value, str):
                    # Use re.sub to replace all placeholders in the string
                    resolved_value_str = re.sub(r"\{\{(.*?)\}\}", lambda m: str(replace_placeholder(m)), value)
                    resolved_params[key] = resolved_value_str

                    # Attempt to convert to number if it looks like one and was fully resolved to a number-like string
                    try:
                        if "." in str(resolved_params[key]): # Convert to string for checking decimal point
                            resolved_params[key] = float(resolved_params[key])
                        else:
                            resolved_params[key] = int(resolved_params[key])
                    except ValueError:
                        pass # Not a number, keep as string
                else:
                    resolved_params[key] = value

            tool_result = self._execute_tool(tool_name, resolved_params)
            results[current_step_name] = tool_result

            if "error" in tool_result:
                current_step_name = step.get("next_step_on_failure")
            else:
                last_successful_step_name = current_step_name # Update last successful step
                current_step_name = step.get("next_step_on_success")

        # Determine the final response based on the last successful step
        final_response_content = None
        print(f"DEBUG: last_successful_step_name: {last_successful_step_name}")
        print(f"DEBUG: results: {results}")

        if last_successful_step_name and "output" in results.get(last_successful_step_name, {}):
            final_response_content = results[last_successful_step_name]["output"]

        # If the final response is still a placeholder, try to resolve it
        if isinstance(final_response_content, str):
            match = re.match(r"\{\{(.*?)\}\}", final_response_content)
            if match:
                final_response_content = replace_placeholder(match)

        if final_response_content is not None:
            results["final_response"] = {"output": final_response_content}
        else:
            results["final_response"] = {"output": "Workflow completed, but no explicit final response was generated."}

        return results
