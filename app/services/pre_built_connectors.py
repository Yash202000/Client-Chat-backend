
import os
import importlib.util
from typing import Dict, Any

def load_pre_built_connectors() -> Dict[str, Any]:
    """
    Dynamically loads all pre-built connector schemas from this directory.
    Each tool file should contain a TOOL_SCHEMA dictionary.
    """
    connectors = {}
    # Point to the correct, isolated directory for tool definitions
    connectors_dir = os.path.join(os.path.dirname(__file__), "connector_definitions")

    if not os.path.exists(connectors_dir):
        return {}

    for filename in os.listdir(connectors_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            module_path = os.path.join(connectors_dir, filename)
            
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                if hasattr(module, "TOOL_SCHEMA"):
                    tool_schema = getattr(module, "TOOL_SCHEMA")
                    # We only need the schema for the definition, not the execute function here.
                    schema_copy = tool_schema.copy()
                    schema_copy.pop("execute", None)
                    connectors[tool_schema["name"]] = schema_copy

    return connectors

PRE_BUILT_CONNECTORS = load_pre_built_connectors()
