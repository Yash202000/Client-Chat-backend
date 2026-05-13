
import json
from collections import deque

class GraphExecutionEngine:
    def __init__(self, workflow_data):
        # Handle None or empty workflow_data
        if workflow_data is None:
            workflow_data = {}

        self.nodes = {node['id']: node for node in workflow_data.get('nodes', [])}
        self.edges = workflow_data.get('edges', [])
        self.adjacency_list = self._build_adjacency_list()

    def _build_adjacency_list(self):
        adj = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            source, target = edge['source'], edge['target']
            adj[source].append(target)
        return adj

    def find_start_node(self):
        in_degrees = {node_id: 0 for node_id in self.nodes}
        for edge in self.edges:
            in_degrees[edge['target']] += 1
        
        start_nodes = [node_id for node_id, degree in in_degrees.items() if degree == 0]
        # In a valid workflow, there should be exactly one start node.
        # We can add more robust error handling here later.
        return start_nodes[0] if start_nodes else None

    def get_next_node(self, current_node_id, result):
        
        current_node = self.nodes.get(current_node_id)
        if not current_node:
            return None

        node_type = current_node.get('type')

        if node_type == 'condition':
            if result and 'output' in result:
                conditional_result = result['output']

                # Determine which handle to find based on result type
                if isinstance(conditional_result, bool):
                    # Legacy single condition: true/false
                    handle_to_find = 'true' if conditional_result else 'false'
                elif isinstance(conditional_result, int):
                    # Multi-condition: index (0, 1, 2, etc.)
                    handle_to_find = str(conditional_result)
                elif isinstance(conditional_result, str):
                    # Multi-condition: "else" or custom handle name
                    handle_to_find = conditional_result
                else:
                    return None


                edge = next((edge for edge in self.edges if edge['source'] == current_node_id and edge.get('sourceHandle') == handle_to_find), None)

                if edge:
                    return edge['target']
                else:
                    return None
            else:
                return None

        elif node_type == 'question_classifier':
            # Routes based on LLM classification result
            if result and 'output' in result:
                class_output = result['output']

                # Look for edge with sourceHandle matching the classification result
                edge = next((e for e in self.edges
                            if e['source'] == current_node_id
                            and e.get('sourceHandle') == class_output), None)

                if edge:
                    return edge['target']

                # If no matching class edge, try default
                default_edge = next((e for e in self.edges
                                    if e['source'] == current_node_id
                                    and e.get('sourceHandle') == 'default'), None)
                if default_edge:
                    return default_edge['target']

                return None
            else:
                return None

        elif node_type in ('foreach_loop', 'while_loop'):
            # Loop nodes return either:
            # - {"output": "loop"} to continue iterating (follow 'loop' handle)
            # - {"output": "exit"} when loop is complete (follow 'exit' handle)
            if result and 'output' in result:
                handle_to_find = result['output']  # 'loop' or 'exit'

                edge = next(
                    (e for e in self.edges
                     if e['source'] == current_node_id
                     and e.get('sourceHandle') == handle_to_find),
                    None
                )

                if edge:
                    return edge['target']
                else:
                    return None
            else:
                return None

        elif result and "error" in result:
            error_edge = next((edge for edge in self.edges if edge['source'] == current_node_id and edge.get('sourceHandle') == 'error'), None)
            if error_edge:
                return error_edge['target']
            return None
            
        else:
            # Default path for non-conditional, non-error nodes
            edge = next((edge for edge in self.edges if edge['source'] == current_node_id), None)
            if edge:
                return edge['target']
            return None
