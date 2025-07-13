workflow_name = args.get("workflow_name")
inputs = args.get("inputs")
exec_globals["result"] = {"workflow_name": workflow_name, "inputs": inputs}