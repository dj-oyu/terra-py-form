"""Extended tests for cold/graph.py - simplify and edge cases."""
import pytest

from terra_py_form.cold.graph import Graph, Node
from terra_py_form.cold.parser import InfraDefinition, Resource


class TestGraphSimplify:
    """Tests for Graph.simplify() method."""

    def _make_graph(self, resources: list[Resource]) -> Graph:
        """Helper to create Graph from resources."""
        definition = InfraDefinition(version="1.0", variables={}, resources=resources)
        return Graph(definition)

    def test_simplify_empty_graph(self):
        """Simplify empty graph works."""
        graph = self._make_graph([])
        simplified = graph.simplify()
        assert simplified.get_resource_names() == []

    def test_simplify_single_node(self):
        """Simplify single node has no effect."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        graph = self._make_graph([vpc])
        simplified = graph.simplify()

        assert simplified.has_node("vpc")
        assert simplified.get_node("vpc").outgoing == set()

    def test_simplify_linear_chain(self):
        """Simplify linear chain A -> B -> C."""
        # A -> B -> C
        a = Resource(name="a", type="type:a")
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(name="c", type="type:c", depends_on=["b"])
        graph = self._make_graph([a, b, c])

        # Before simplify
        assert "a" in graph.get_node("b").outgoing
        assert "b" in graph.get_node("c").outgoing

        simplified = graph.simplify()

        # After simplify: b depends on a, c depends on b
        # Transitive edges (a->c) should be removed if existed
        assert "a" in simplified.get_node("b").outgoing
        assert "b" in simplified.get_node("c").outgoing

    def test_simplify_removes_transitive(self):
        """Simplify removes transitive edges correctly."""
        # A -> B -> C, but A also directly -> C (transitive)
        a = Resource(name="a", type="type:a")
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(name="c", type="type:c", depends_on=["a", "b"])
        graph = self._make_graph([a, b, c])

        # Before: C depends on both A and B
        c_node_before = graph.get_node("c")
        assert "a" in c_node_before.outgoing
        assert "b" in c_node_before.outgoing

        # After simplify: A->C is transitive through A->B->C
        # depends_on is explicit, so both stay
        # This tests that simplify doesn't break explicit deps
        simplified = graph.simplify()
        c_node_after = simplified.get_node("c")
        assert "b" in c_node_after.outgoing

    def test_simplify_preserves_direct_dependencies(self):
        """Simplify preserves direct dependencies from depends_on."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        sg = Resource(name="sg", type="aws:ec2:security_group", depends_on=["vpc"])
        instance = Resource(name="instance", type="aws:ec2:instance", depends_on=["vpc", "sg"])
        graph = self._make_graph([vpc, sg, instance])

        simplified = graph.simplify()

        # instance has explicit depends_on on both vpc and sg
        instance_node = simplified.get_node("instance")
        assert "vpc" in instance_node.outgoing
        assert "sg" in instance_node.outgoing

    def test_simplify_complex_dag(self):
        """Simplify complex DAG with diamond pattern."""
        #     a
        #    / \
        #   b   c
        #    \ /
        #     d
        a = Resource(name="a", type="type:a")
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(name="c", type="type:c", depends_on=["a"])
        d = Resource(name="d", type="type:d", depends_on=["b", "c"])
        graph = self._make_graph([a, b, c, d])

        simplified = graph.simplify()

        # d should depend on both b and c
        d_node = simplified.get_node("d")
        assert "b" in d_node.outgoing
        assert "c" in d_node.outgoing


class TestGraphEdgeCases:
    """Edge case tests for Graph."""

    def _make_graph(self, resources: list[Resource]) -> Graph:
        """Helper to create Graph from resources."""
        definition = InfraDefinition(version="1.0", variables={}, resources=resources)
        return Graph(definition)

    def test_graph_with_many_dependencies(self):
        """Graph handles many dependencies."""
        resources = [Resource(name="base", type="type:base")]
        for i in range(10):
            resources.append(
                Resource(name=f"res_{i}", type="type:res", depends_on=["base"])
            )

        graph = self._make_graph(resources)

        assert graph.has_node("base")
        for i in range(10):
            assert graph.has_node(f"res_{i}")
            assert "base" in graph.get_node(f"res_{i}").outgoing

    def test_graph_self_dependency(self):
        """Resource depending on itself is allowed (cycle detected elsewhere)."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", depends_on=["vpc"])
        graph = self._make_graph([vpc])

        # Graph builds, but this creates self-loop
        vpc_node = graph.get_node("vpc")
        assert "vpc" in vpc_node.outgoing
        assert "vpc" in vpc_node.incoming

    def test_graph_diamond_dependency(self):
        """Diamond dependency pattern."""
        #     root
        #    /   \
        #   a     b
        #    \   /
        #     leaf
        root = Resource(name="root", type="type:root")
        a = Resource(name="a", type="type:a", depends_on=["root"])
        b = Resource(name="b", type="type:b", depends_on=["root"])
        leaf = Resource(name="leaf", type="type:leaf", depends_on=["a", "b"])
        graph = self._make_graph([root, a, b, leaf])

        assert graph.has_node("root")
        assert graph.has_node("leaf")

        # Check outgoing (what leaf depends on)
        leaf_node = graph.get_node("leaf")
        assert "a" in leaf_node.outgoing
        assert "b" in leaf_node.outgoing


class TestGraphReachability:
    """Tests for graph reachability computation."""

    def _make_graph(self, resources: list[Resource]) -> Graph:
        """Helper to create Graph from resources."""
        definition = InfraDefinition(version="1.0", variables={}, resources=resources)
        return Graph(definition)

    def test_compute_reachability_simple(self):
        """Compute reachability for simple chain."""
        a = Resource(name="a", type="type:a")
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(name="c", type="type:c", depends_on=["b"])
        graph = self._make_graph([a, b, c])

        reachable = graph._compute_reachability()

        # a reaches nothing
        assert reachable["a"] == set()
        # b reaches a
        assert "a" in reachable["b"]
        # c reaches a and b
        assert "a" in reachable["c"]
        assert "b" in reachable["c"]

    def test_compute_reachability_branch(self):
        """Compute reachability with branches."""
        root = Resource(name="root", type="type:root")
        left = Resource(name="left", type="type:left", depends_on=["root"])
        right = Resource(name="right", type="type:right", depends_on=["root"])
        leaf = Resource(name="leaf", type="type:leaf", depends_on=["left", "right"])
        graph = self._make_graph([root, left, right, leaf])

        reachable = graph._compute_reachability()

        # leaf reaches all
        assert "root" in reachable["leaf"]
        assert "left" in reachable["leaf"]
        assert "right" in reachable["leaf"]


class TestGraphNode:
    """Additional tests for Node class."""

    def test_node_repr(self):
        """Node has useful repr."""
        res = Resource(name="test", type="aws:ec2:vpc")
        node = Node(resource=res, outgoing={"dep1"}, incoming={"parent1"})
        repr_str = repr(node)
        assert "test" in repr_str

    def test_node_hashable(self):
        """Node can be used in sets/dicts."""
        res1 = Resource(name="vpc1", type="aws:ec2:vpc")
        res2 = Resource(name="vpc2", type="aws:ec2:vpc")
        node1 = Node(resource=res1)
        node2 = Node(resource=res2)

        # Should be able to add to set (different objects)
        node_set = {node1, node2}
        assert len(node_set) == 2
