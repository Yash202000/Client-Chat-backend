
from app.services import workflow_service, workflow_execution_service

def run(params: dict, config: dict):
    """
    Finds and triggers a workflow based on the user's query.
    """
    debug_info = {
        "message": "Starting trigger_workflow tool execution.",
        "received_params": params,
        "received_config_keys": list(config.keys())
    }

    try:
        db = config.get("db")
        company_id = config.get("company_id")
        user_query = params.get("user_query")
        inputs = params.get("inputs", {})

        if not all([db, company_id, user_query]):
            debug_info["error"] = "Missing required configuration or parameters."
            return debug_info

        debug_info["step"] = "Finding similar workflow"
        debug_info["user_query"] = user_query
        
        # Find the most similar workflow based on the user's query
        workflow = workflow_service.find_similar_workflow(db, company_id, user_query)
        
        print(workflow)
        debug_info["found_workflow"] = workflow.name if workflow else "None"

        if not workflow:
            debug_info["error"] = f"No suitable workflow found for the query: '{user_query}'"
            # To help debug, let's list available workflows
            all_workflows = workflow_service.get_workflows(db, company_id)
            debug_info["available_workflows"] = [wf.name for wf in all_workflows]
            return debug_info

        debug_info["step"] = "Executing workflow"
        debug_info["workflow_to_execute"] = workflow.name
        debug_info["workflow_inputs"] = inputs

        # Execute the found workflow
        result = workflow_execution_service.execute_workflow(db, workflow.id, inputs)
        
        debug_info["step"] = "Workflow execution finished"
        debug_info["execution_result"] = result
        
        # The final result should be the workflow's output
        return result

    except Exception as e:
        debug_info["error"] = "An exception occurred during tool execution."
        debug_info["exception_details"] = str(e)
        return debug_info
