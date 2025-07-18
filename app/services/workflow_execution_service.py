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

        local_scope = {}
        execution_globals = {
            "db": self.db, # Make the database session available
            # Add other services or utilities here if needed by tools
        }

        try:
            # Execute the tool's code, which defines the 'run' function
            exec(tool.code, execution_globals, local_scope)
            
            # Get the 'run' function from the local scope
            tool_function = local_scope.get("run")
            
            if not callable(tool_function):
                return {"error": "Tool code does not define a callable 'run' function"}

            # Prepare the config for the tool
            config = {
                "db": self.db,
                # If company_id is needed, it would need to be passed into execute_workflow
                # and then into this config.
            }

            # Call the tool's 'run' function with the provided parameters and stored configuration
            result = tool_function(params=params, config=config)
            return {"output": result}
        except Exception as e:
            return {"error": f"Error executing tool {tool_name}: {e}"}

    def execute_workflow(self, workflow: Workflow, initial_context: dict = None):
        print(f"DEBUG: INITIAL OCNTEXT : {initial_context}")
        print(f"DEBUG: Starting workflow execution for workflow: {workflow.name}")
        print(f"DEBUG: Workflow steps received: {workflow.steps}")
        
        print()

        if not workflow or not workflow.steps:
            print("DEBUG: Invalid workflow or no steps defined.")
            return {"error": "Invalid workflow or no steps defined."}
        
        context = initial_context if initial_context is not None else {}
        results = {}
        current_step_name = "step1" # Assuming the first step is always named 'step1'
        last_successful_step_name = None # Track the last successful step

        workflow_steps = workflow.steps.get("steps", {}) # Access the nested 'steps' dictionary
        print(f"DEBUG: Extracted workflow_steps dictionary: {workflow_steps}")

        def replace_placeholder(match):
            path = match.group(1).strip().split(".")
            if len(path) == 2 and path[0] == "context":
                context_key = path[1]
                value_from_context = context.get(context_key)
                print(f"DEBUG: Resolving context placeholder {{context.{context_key}}}. Value: {value_from_context}")
                return str(value_from_context) if value_from_context is not None else match.group(0)
            elif len(path) == 2 and path[1] == "output":
                prev_step_name = path[0]
                output_value = results.get(prev_step_name, {}).get("output")
                print(f"DEBUG: Resolving output placeholder {{{prev_step_name}.output}}. Value: {output_value}")
                return str(output_value) if output_value is not None else match.group(0)
            return match.group(0)

        while current_step_name:
            print(f"DEBUG: Current step name: {current_step_name}")
            step = workflow_steps.get(current_step_name)
            if not step:
                print(f"DEBUG: Step '{current_step_name}' not found. Exiting workflow.")
                break

            print(f"DEBUG: Processing step: {step}")
            tool_name = step.get("tool")
            params = step.get("params", {})
            print(f"DEBUG: Tool name: {tool_name}, Raw params: {params}")

            resolved_params = {}
            for key, value in params.items():
                if isinstance(value, str):
                    # Use a temporary variable to store the resolved value, which might not be a string
                    resolved_temp_value = re.sub(r"\{\{(.*?)\}\}", replace_placeholder, value)
                    
                    # If the resolved_temp_value is not a string, it means replace_placeholder returned a direct value (e.g., int, float)
                    if not isinstance(resolved_temp_value, str):
                        resolved_params[key] = resolved_temp_value
                    else:
                        # If it's still a string, try to convert it to a number if applicable
                        try:
                            if '.' in resolved_temp_value:
                                resolved_params[key] = float(resolved_temp_value)
                            else:
                                resolved_params[key] = int(resolved_temp_value)
                        except ValueError:
                            # If conversion fails, keep it as a string
                            resolved_params[key] = resolved_temp_value
                else:
                    resolved_params[key] = value
            print(f"DEBUG: Resolved params: {resolved_params}")

            tool_result = self._execute_tool(tool_name, resolved_params)
            results[current_step_name] = tool_result
            print(f"DEBUG: Tool execution result for '{current_step_name}': {tool_result}")

            if "error" in tool_result:
                print(f"DEBUG: Error in step '{current_step_name}'. Moving to next_step_on_failure.")
                current_step_name = step.get("next_step_on_failure")
            else:
                print(f"DEBUG: Step '{current_step_name}' successful. Moving to next_step_on_success.")
                last_successful_step_name = current_step_name
                current_step_name = step.get("next_step_on_success")

        print(f"DEBUG: Workflow execution finished. Last successful step: {last_successful_step_name}")
        print(f"DEBUG: All results: {results}")

        final_response_content = None
        if last_successful_step_name and "output" in results.get(last_successful_step_name, {}):
            final_response_content = str(results[last_successful_step_name]["output"])
            print(f"DEBUG: Initial final_response_content: {final_response_content}")

        if isinstance(final_response_content, str):
            match = re.match(r"\{\{(.*?)\}\}", final_response_content)
            if match:
                resolved_final_response = replace_placeholder(match)
                print(f"DEBUG: Resolved final_response_content from placeholder: {resolved_final_response}")
                final_response_content = str(resolved_final_response)

        if final_response_content is not None:
            results["final_response"] = {"output": final_response_content}
            print(f"DEBUG: Final response set: {results["final_response"]}")
        else:
            results["final_response"] = {"output": "Workflow completed, but no explicit final response was generated."}
            print(f"DEBUG: No explicit final response generated. Defaulting to: {results["final_response"]}")

        return results
