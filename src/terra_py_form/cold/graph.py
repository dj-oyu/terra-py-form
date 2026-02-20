"""Dependency graph construction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Set

from terra_py_form.cold.parser import InfraDefinition, Resource


@dataclass
class Node:
    """Graph node representing a resource."""

    resource: Resource
    outgoing: Set[str] = field(default_factory=set)  # dependencies (what this node depends on)
    incoming: Set[str] = field(default_factory=set)  # dependents (what depends on this node)

    def __hash__(self) -> int:
        return hash(self.resource.name)


class Graph:
    """Directed Acyclic Graph (DAG) of resource dependencies."""

    def __init__(self, definition: InfraDefinition):
        self.definition = definition
        self.nodes: dict[str, Node] = {}
        self._build(definition)

    def _build(self, definition: InfraDefinition) -> None:
        """Build graph from InfraDefinition."""
        # Create nodes for all resources
        for res in definition.resources:
            self.nodes[res.name] = Node(resource=res)

        # Add edges based on dependencies
        for res in definition.resources:
            node = self.nodes[res.name]

            # 1. Explicit depends_on
            # Edge direction: dependency -> dependent
            # If A depends_on B, B must be created first, so edge is B -> A
            for dep in res.depends_on:
                self._add_edge(dep, res.name)

            # 2. Implicit dependencies from ${ref(...)}
            for ref in res.source_refs:
                self._add_edge(ref, res.name)

    def _add_edge(self, from_name: str, to_name: str) -> None:
        """Add directed edge from -> to.
        
        Edge direction: dependent -> dependency
        If A depends_on B, edge is A -> B (A points to what it depends on)
        So: A.outgoing = {B}, B.incoming = {A}
        """
        if from_name not in self.nodes:
            raise KeyError(f"Dependency '{from_name}' not found")
        if to_name not in self.nodes:
            raise KeyError(f"Resource '{to_name}' not found in graph")

        # Edge points from dependent TO dependency
        # If A depends_on B: A -> B
        # A.outgoing contains B (A depends on B)
        # B.incoming contains A (A is a dependent of B)
        self.nodes[to_name].outgoing.add(from_name)
        self.nodes[from_name].incoming.add(to_name)

    def simplify(self) -> Graph:
        """Remove transitive edges to simplify the graph.

        If A -> B -> C and A doesn't directly reference C in depends_on,
        then A -> C edge can be removed (A -> B -> C is sufficient).

        Explicit depends_on edges are always preserved.
        """
        # Build transitive closure first (all reachable nodes)
        all_reachable = self._compute_reachability()

        # Compute direct dependencies (explicit depends_on + source_refs)
        direct_deps: dict[str, Set[str]] = {}
        for name, node in self.nodes.items():
            direct_deps[name] = set(node.outgoing)

        # Remove transitive edges
        for node_name in self.nodes:
            node = self.nodes[node_name]
            outgoing_copy = set(node.outgoing)
            for direct_dep in outgoing_copy:
                # Check if there's an indirect path through another node
                for intermediate in outgoing_copy:
                    if intermediate == direct_dep:
                        continue
                    # If direct_dep is reachable through intermediate
                    # (and direct_dep is NOT an explicit dependency of node_name)
                    if direct_dep in all_reachable.get(intermediate, set()):
                        if direct_dep in direct_deps.get(node_name, set()):
                            # Explicit dependency - preserve it
                            continue
                        # This edge is transitive (not explicit), remove it
                        node.outgoing.discard(direct_dep)
                        if node_name in self.nodes[direct_dep].incoming:
                            self.nodes[direct_dep].incoming.discard(node_name)

        return self

    def _compute_reachability(self) -> dict[str, Set[str]]:
        """Compute all nodes reachable from each node (transitive closure)."""
        reachable: dict[str, Set[str]] = {name: set() for name in self.nodes}

        # Floyd-Warshall-like approach (since graph is small)
        for node_name in self.nodes:
            visited = set()
            stack = list(self.nodes[node_name].outgoing)
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                reachable[node_name].add(current)
                stack.extend(self.nodes[current].outgoing - visited)

        return reachable

    def get_resource_names(self) -> list[str]:
        """Get all resource names in topological order (roughly)."""
        return list(self.nodes.keys())

    def get_node(self, name: str) -> Node:
        """Get node by resource name."""
        return self.nodes[name]

    def has_node(self, name: str) -> bool:
        """Check if node exists."""
        return name in self.nodes
