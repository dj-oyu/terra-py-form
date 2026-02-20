"""Dependency resolution: cycle detection and topological sort."""
from __future__ import annotations

from typing import Optional

from terra_py_form.cold.graph import Graph


class CycleError(Exception):
    """Circular dependency detected."""

    def __init__(self, path: list[str]):
        self.path = path
        super().__init__(f"Circular dependency: {' → '.join(path)}")


class Solver:
    """Resolve dependencies: detect cycles, compute topological order."""

    def __init__(self, graph: Graph):
        self.graph = graph

    def detect_cycle(self) -> Optional[list[str]]:
        """Detect circular dependencies using DFS.

        Returns:
            List of resource names forming the cycle, or None if no cycle.
        """
        # 0 = unvisited, 1 = in progress, 2 = completed
        state: dict[str, int] = {name: 0 for name in self.graph.nodes}
        path: list[str] = []

        def dfs(node_name: str) -> Optional[list[str]]:
            """DFS to find cycle."""
            state[node_name] = 1
            path.append(node_name)

            for neighbor in self.graph.nodes[node_name].outgoing:
                if state[neighbor] == 1:
                    # Found cycle - extract cycle path
                    cycle_start = path.index(neighbor)
                    cycle_path = path[cycle_start:] + [neighbor]
                    return cycle_path
                elif state[neighbor] == 0:
                    result = dfs(neighbor)
                    if result:
                        return result

            path.pop()
            state[node_name] = 2
            return None

        for node_name in self.graph.nodes:
            if state[node_name] == 0:
                result = dfs(node_name)
                if result:
                    return result

        return None

    def topological_sort(self) -> list[str]:
        """Compute topological order using Kahn's algorithm.

        Returns:
            List of resource names in apply order.

        Raises:
            CycleError: If circular dependency detected.
        """
        # Check for cycles first
        cycle = self.detect_cycle()
        if cycle:
            raise CycleError(cycle)

        # Kahn's algorithm - use outgoing (dependencies) for in_degree
        # If A depends on B (A -> B in our graph), we need to apply B before A
        # So in_degree = number of dependencies = len(outgoing)
        in_degree = {name: len(self.graph.nodes[name].outgoing) for name in self.graph.nodes}
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Sort for deterministic output
            queue.sort()
            node_name = queue.pop(0)
            result.append(node_name)

            # Reduce in_degree of nodes that depend on this node (incoming)
            for dependent in self.graph.nodes[node_name].incoming:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self.graph.nodes):
            # Should not happen if cycle check passed, but safety check
            raise CycleError(["Unknown cycle"])

        return result

    def get_execution_order(self) -> list[str]:
        """Get resources in the order they should be applied.

        Alias for topological_sort() for clarity.
        """
        return self.topological_sort()

    def get_dependencies(self, resource_name: str) -> list[str]:
        """Get all dependencies of a resource (direct only)."""
        if resource_name not in self.graph.nodes:
            raise KeyError(f"Resource '{resource_name}' not found")
        return list(self.graph.nodes[resource_name].outgoing)

    def get_dependents(self, resource_name: str) -> list[str]:
        """Get all resources that depend on this resource (direct only)."""
        if resource_name not in self.graph.nodes:
            raise KeyError(f"Resource '{resource_name}' not found")
        return list(self.graph.nodes[resource_name].incoming)
