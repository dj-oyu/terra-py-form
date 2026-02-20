"""Plan/Compute diffs between desired and current state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from terra_py_form.cold.graph import Graph
from terra_py_form.cold.state import State


Action = Literal["create", "update", "delete", "noop"]


@dataclass
class Diff:
    """Resource difference."""

    resource_name: str
    resource_type: str
    action: Action
    before: dict | None = None  # old state (None for create)
    after: dict | None = None  # new desired state (None for delete)
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)  # field: (old, new)

    def __repr__(self) -> str:
        return f"Diff({self.resource_name}: {self.action})"


class Planner:
    """Compute differences between desired and current state."""

    def __init__(self, state: State):
        self.state = state

    def plan(self, graph: Graph) -> list[Diff]:
        """Compute diffs for all resources in the graph.

        Args:
            graph: The desired state graph.

        Returns:
            List of Diff objects in dependency order.
        """
        diffs: list[Diff] = []

        for resource_name in graph.get_resource_names():
            node = graph.get_node(resource_name)
            resource = node.resource

            # Get current state
            current_state = self.state.resources.get(resource_name)

            if current_state is None:
                # Resource doesn't exist - will be created
                diff = Diff(
                    resource_name=resource_name,
                    resource_type=resource.type,
                    action="create",
                    before=None,
                    after=resource.properties,
                    changes={},
                )
            else:
                # Resource exists - check for changes
                diff = self._compute_diff(
                    resource_name=resource_name,
                    desired=resource.properties,
                    actual=current_state.properties,
                    resource_type=resource.type,
                )

            diffs.append(diff)

        return diffs

    def _compute_diff(
        self,
        resource_name: str,
        desired: dict,
        actual: dict,
        resource_type: str,
    ) -> Diff:
        """Compute diff between desired and actual state."""
        changes: dict[str, tuple[Any, Any]] = {}

        # Check all desired keys
        for key, desired_value in desired.items():
            actual_value = actual.get(key)
            if actual_value != desired_value:
                changes[key] = (actual_value, desired_value)

        # Check for keys that were removed
        for key in actual:
            if key not in desired:
                changes[key] = (actual[key], None)

        if changes:
            return Diff(
                resource_name=resource_name,
                resource_type=resource_type,
                action="update",
                before=actual,
                after=desired,
                changes=changes,
            )
        else:
            return Diff(
                resource_name=resource_name,
                resource_type=resource_type,
                action="noop",
                before=actual,
                after=desired,
                changes={},
            )

    def plan_with_order(self, graph: Graph) -> list[Diff]:
        """Compute diffs in topological order (proper dependency order)."""
        from terra_py_form.cold.solver import Solver

        solver = Solver(graph)
        order = solver.topological_sort()

        diffs = []
        for resource_name in order:
            node = graph.get_node(resource_name)
            resource = node.resource

            current_state = self.state.resources.get(resource_name)

            if current_state is None:
                diff = Diff(
                    resource_name=resource_name,
                    resource_type=resource.type,
                    action="create",
                    before=None,
                    after=resource.properties,
                    changes={},
                )
            else:
                diff = self._compute_diff(
                    resource_name=resource_name,
                    desired=resource.properties,
                    actual=current_state.properties,
                    resource_type=resource.type,
                )

            diffs.append(diff)

        return diffs
