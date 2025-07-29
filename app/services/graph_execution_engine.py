
import json
from collections import deque

class GraphExecutionEngine:
    def __init__(self, workflow_data):
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
        if result and "error" in result:
            error_edge = next((edge for edge in self.edges if edge['source'] == current_node_id and edge.get('sourceHandle') == 'error'), None)
            return error_edge['target'] if error_edge else None

        if self.nodes[current_node_id].get('type') == 'conditional':
            conditional_result = result.get('output')
            if conditional_result:
                true_edge = next((edge for edge in self.edges if edge['source'] == current_node_id and edge.get('sourceHandle') == 'true'), None)
                return true_edge['target'] if true_edge else None
            else:
                false_edge = next((edge for edge in self.edges if edge['source'] == current_node_id and edge.get('sourceHandle') == 'false'), None)
                return false_edge['target'] if false_edge else None
        else:
            # For non-conditional, non-error cases, there is only one output
            edge = next((edge for edge in self.edges if edge['source'] == current_node_id), None)
            return edge['target'] if edge else None
