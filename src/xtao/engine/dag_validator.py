"""DAG validator - Structure validation and topological analysis for DAG-style Plan.

Provides cycle detection, node reference validation, topological sorting, and ready node computation.
Code-level deterministic detection, does not depend on LLM.
"""

from collections import deque

from xtao.models import DAGPlan


class DAGValidator:
    """DAG validator.

    Provides deterministic validation of DAG structure (does not depend on LLM):
    - Cycle detection (DFS three-color marking)
    - Node reference validity validation
    - Topological sorting (Kahn's algorithm)
    - Ready node computation
    """

    def validate(self, dag: DAGPlan) -> list[str]:
        """Validate DAG, return list of errors.

        Empty list means validation passed. Check items include:
        - Node ID uniqueness
        - Node reference validity (IDs in depends_on must exist)
        - Cycle detection
        """
        errors: list[str] = []

        # Check node ID uniqueness
        seen_ids: set[str] = set()
        for node in dag.nodes:
            if node.id in seen_ids:
                errors.append(f"Duplicate node ID: {node.id}")
            seen_ids.add(node.id)

        # Node reference validity
        errors.extend(self.validate_node_references(dag))

        # Cycle detection
        cycles = self.detect_cycles(dag)
        for cycle in cycles:
            errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")

        # Edge reference validity
        node_ids = {node.id for node in dag.nodes}
        for edge in dag.edges:
            if edge.src not in node_ids:
                errors.append(f"Edge source node does not exist: {edge.src}")
            if edge.dst not in node_ids:
                errors.append(f"Edge target node does not exist: {edge.dst}")

        return errors

    def detect_cycles(self, dag: DAGPlan) -> list[list[str]]:
        """Detect circular dependencies using DFS three-color marking.

        Returns list of cycle paths; empty list means no cycles.
        Each cycle path is a list of node IDs, with the same first and last element.
        """
        node_ids = {node.id for node in dag.nodes}

        # Build dependency graph: node -> list of nodes it depends on
        # If A depends_on B, then edge A -> B (A points to its dependency)
        graph: dict[str, list[str]] = {node.id: [] for node in dag.nodes}
        for node in dag.nodes:
            for dep in node.depends_on:
                if dep in node_ids:
                    graph[node.id].append(dep)

        # In edges, src -> dst means src must complete first, i.e., dst depends on src
        for edge in dag.edges:
            if edge.src in node_ids and edge.dst in node_ids:
                graph[edge.dst].append(edge.src)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {nid: WHITE for nid in graph}
        cycles: list[list[str]] = []

        def _dfs(node: str, path: list[str]) -> None:
            """DFS traversal, detect cycles."""
            color[node] = GRAY
            path.append(node)
            for dep in graph.get(node, []):
                if color.get(dep, BLACK) == GRAY:
                    # Cycle found, extract cycle path
                    cycle_start = path.index(dep)
                    cycles.append(path[cycle_start:] + [dep])
                elif color.get(dep, BLACK) == WHITE:
                    _dfs(dep, path)
            path.pop()
            color[node] = BLACK

        for node_id in graph:
            if color[node_id] == WHITE:
                _dfs(node_id, [])

        return cycles

    def validate_node_references(self, dag: DAGPlan) -> list[str]:
        """Validate node reference validity.

        IDs in depends_on must exist in the node list.
        """
        node_ids = {node.id for node in dag.nodes}
        errors: list[str] = []
        for node in dag.nodes:
            for dep in node.depends_on:
                if dep not in node_ids:
                    errors.append(
                        f"Node {node.id} depends on non-existent node: {dep}"
                    )
        return errors

    def get_topological_order(self, dag: DAGPlan) -> list[str]:
        """Return topological sort result using Kahn's algorithm.

        If circular dependencies exist, the partial sort returned excludes nodes in cycles.
        """
        node_ids = {node.id for node in dag.nodes}

        # Build in-degree table and successor table
        # If A depends_on B, then edge B -> A, A's in-degree +1
        in_degree: dict[str, int] = {node.id: 0 for node in dag.nodes}
        successors: dict[str, list[str]] = {node.id: [] for node in dag.nodes}

        for node in dag.nodes:
            for dep in node.depends_on:
                if dep in node_ids:
                    in_degree[node.id] += 1
                    successors[dep].append(node.id)

        for edge in dag.edges:
            if edge.src in node_ids and edge.dst in node_ids:
                in_degree[edge.dst] += 1
                successors[edge.src].append(edge.dst)

        # Kahn's algorithm: start from nodes with in-degree 0
        queue: deque[str] = deque(
            nid for nid, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for succ in successors.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)

        return order

    def get_ready_nodes(
        self, dag: DAGPlan, completed: set[str]
    ) -> list[str]:
        """Get executable nodes (all dependencies completed and itself not completed).

        Args:
            dag: DAG Plan
            completed: Set of completed node IDs

        Returns:
            List of executable node IDs
        """
        ready: list[str] = []
        for node in dag.nodes:
            if node.id in completed:
                continue
            if all(dep in completed for dep in node.depends_on):
                ready.append(node.id)
        return ready
