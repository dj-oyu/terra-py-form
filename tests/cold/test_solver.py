"""Tests for cold/solver.py"""
import pytest

from terra_py_form.cold.graph import Graph
from terra_py_form.cold.parser import InfraDefinition, Resource
from terra_py_form.cold.solver import CycleError, Solver


class TestSolver:
    """Tests for Solver class."""

    def _make_graph(self, resources: list[Resource]) -> Graph:
        """Helper to create Graph from resources."""
        definition = InfraDefinition(version="1.0", variables={}, resources=resources)
        return Graph(definition)

    def test_detect_cycle_no_cycle(self):
        """No cycle returns None."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        assert solver.detect_cycle() is None

    def test_detect_cycle_finds_direct_cycle(self):
        """Direct cycle A -> A is detected."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", depends_on=["vpc"])
        graph = self._make_graph([vpc])

        solver = Solver(graph)
        cycle = solver.detect_cycle()
        assert cycle is not None
        assert "vpc" in cycle

    def test_detect_cycle_finds_two_node_cycle(self):
        """Two-node cycle A -> B -> A is detected."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", depends_on=["subnet"])
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        cycle = solver.detect_cycle()
        assert cycle is not None
        # Cycle should contain both vpc and subnet
        assert "vpc" in cycle
        assert "subnet" in cycle

    def test_detect_cycle_finds_three_node_cycle(self):
        """Three-node cycle is detected."""
        a = Resource(name="a", type="type:a", depends_on=["c"])
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(name="c", type="type:c", depends_on=["b"])
        graph = self._make_graph([a, b, c])

        solver = Solver(graph)
        cycle = solver.detect_cycle()
        assert cycle is not None
        assert set(cycle) == {"a", "b", "c"}

    def test_topological_sort_simple(self):
        """Simple linear dependency."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        order = solver.topological_sort()

        # vpc should come before subnet
        assert order.index("vpc") < order.index("subnet")

    def test_topological_sort_multiple_dependencies(self):
        """Resource with multiple dependencies."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        sg = Resource(name="sg", type="aws:ec2:security_group")
        instance = Resource(name="instance", type="aws:ec2:instance", depends_on=["vpc", "sg"])
        graph = self._make_graph([vpc, sg, instance])

        solver = Solver(graph)
        order = solver.topological_sort()

        # Both vpc and sg should come before instance
        assert order.index("vpc") < order.index("instance")
        assert order.index("sg") < order.index("instance")

    def test_topological_sort_complex_dag(self):
        """Complex DAG with multiple paths."""
        #       vpc
        #      /   \
        #   subnet  sg
        #      \   /
        #      instance
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        sg = Resource(name="sg", type="aws:ec2:security_group", depends_on=["vpc"])
        instance = Resource(name="instance", type="aws:ec2:instance", depends_on=["subnet", "sg"])
        graph = self._make_graph([vpc, subnet, sg, instance])

        solver = Solver(graph)
        order = solver.topological_sort()

        # vpc must be first (no dependencies)
        assert order[0] == "vpc"
        # instance must be last (depends on everything)
        assert order[-1] == "instance"

    def test_topological_sort_raises_on_cycle(self):
        """Cycle raises CycleError."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", depends_on=["subnet"])
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        with pytest.raises(CycleError) as exc_info:
            solver.topological_sort()

        # Error path should contain the cycle
        assert "vpc" in exc_info.value.path

    def test_topological_sort_empty_graph(self):
        """Empty graph returns empty list."""
        graph = self._make_graph([])

        solver = Solver(graph)
        assert solver.topological_sort() == []

    def test_topological_sort_deterministic(self):
        """Same graph produces same order on multiple calls."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        order1 = solver.topological_sort()
        order2 = solver.topological_sort()

        assert order1 == order2

    def test_get_execution_order_alias(self):
        """get_execution_order is alias for topological_sort."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        assert solver.get_execution_order() == solver.topological_sort()

    def test_get_dependencies(self):
        """Get direct dependencies of a resource."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        sg = Resource(name="sg", type="aws:ec2:security_group")
        instance = Resource(name="instance", type="aws:ec2:instance", depends_on=["vpc", "sg"])
        graph = self._make_graph([vpc, sg, instance])

        solver = Solver(graph)
        deps = solver.get_dependencies("instance")

        assert set(deps) == {"vpc", "sg"}

    def test_get_dependencies_not_found(self):
        """Raises KeyError for unknown resource."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        graph = self._make_graph([vpc])

        solver = Solver(graph)
        with pytest.raises(KeyError, match="not found"):
            solver.get_dependencies("nonexistent")

    def test_get_dependents(self):
        """Get resources that depend on this resource."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        sg = Resource(name="sg", type="aws:ec2:security_group", depends_on=["vpc"])
        graph = self._make_graph([vpc, subnet, sg])

        solver = Solver(graph)
        dependents = solver.get_dependents("vpc")

        assert set(dependents) == {"subnet", "sg"}

    def test_get_dependents_not_found(self):
        """Raises KeyError for unknown resource."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        graph = self._make_graph([vpc])

        solver = Solver(graph)
        with pytest.raises(KeyError, match="not found"):
            solver.get_dependents("nonexistent")

    def test_implicit_ref_dependency_order(self):
        """${ref()} creates implicit dependency."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            properties={"vpc_id": "${ref(vpc)}"},
            source_refs=["vpc"],
        )
        graph = self._make_graph([vpc, subnet])

        solver = Solver(graph)
        order = solver.topological_sort()

        # vpc must come before subnet (implicit dependency via ${ref})
        assert order.index("vpc") < order.index("subnet")
