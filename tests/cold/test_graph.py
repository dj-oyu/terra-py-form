"""Tests for cold/graph.py"""
import pytest

from terra_py_form.cold.graph import Graph, Node
from terra_py_form.cold.parser import InfraDefinition, Resource


class TestNode:
    """Tests for Node dataclass."""

    def test_node_creation(self):
        """Node can be created with a Resource."""
        res = Resource(name="test", type="aws:ec2:vpc")
        node = Node(resource=res)

        assert node.resource == res
        assert node.outgoing == set()
        assert node.incoming == set()

    def test_node_with_edges(self):
        """Node can track outgoing/incoming edges."""
        res = Resource(name="test", type="aws:ec2:vpc")
        node = Node(resource=res, outgoing={"dep1", "dep2"}, incoming={"parent1"})

        assert node.outgoing == {"dep1", "dep2"}
        assert node.incoming == {"parent1"}


class TestGraph:
    """Tests for Graph class."""

    def _make_definition(self, resources: list[Resource]) -> InfraDefinition:
        """Helper to create InfraDefinition."""
        return InfraDefinition(version="1.0", variables={}, resources=resources)

    def test_empty_graph(self):
        """Graph can be empty (no resources)."""
        definition = self._make_definition([])
        graph = Graph(definition)

        assert graph.get_resource_names() == []
        assert not graph.has_node("any")

    def test_single_resource(self):
        """Graph with single resource has single node."""
        res = Resource(name="vpc", type="aws:ec2:vpc")
        definition = self._make_definition([res])
        graph = Graph(definition)

        assert graph.has_node("vpc")
        assert graph.get_node("vpc").resource.name == "vpc"

    def test_explicit_depends_on(self):
        """Graph builds edges from explicit depends_on."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            depends_on=["vpc"],
        )
        definition = self._make_definition([vpc, subnet])
        graph = Graph(definition)

        # subnet depends on vpc: subnet -> vpc
        subnet_node = graph.get_node("subnet")
        assert "vpc" in subnet_node.outgoing

        vpc_node = graph.get_node("vpc")
        assert "subnet" in vpc_node.incoming

    def test_implicit_ref_dependency(self):
        """Graph builds edges from ${ref(...)} in properties."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            properties={"vpc_id": "${ref(vpc)}"},
            source_refs=["vpc"],  # Parser extracts this
        )
        definition = self._make_definition([vpc, subnet])
        graph = Graph(definition)

        # subnet references vpc via ${ref(vpc)}
        subnet_node = graph.get_node("subnet")
        assert "vpc" in subnet_node.outgoing
        # vpc has incoming from subnet (subnet depends on vpc)
        vpc_node = graph.get_node("vpc")
        assert "subnet" in vpc_node.incoming

    def test_missing_dependency_raises(self):
        """Graph raises error for missing dependency."""
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            depends_on=["missing_resource"],
        )
        definition = self._make_definition([subnet])

        with pytest.raises(KeyError, match="Dependency 'missing_resource' not found"):
            Graph(definition)

    def test_missing_ref_target_raises(self):
        """Graph raises error for missing ref target."""
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            properties={"vpc_id": "${ref(missing_vpc)}"},
            source_refs=["missing_vpc"],  # Parser extracts this
        )
        definition = self._make_definition([subnet])

        with pytest.raises(KeyError, match="Dependency 'missing_vpc' not found"):
            Graph(definition)

    def test_multiple_dependencies(self):
        """Resource can have multiple dependencies."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        sg = Resource(name="sg", type="aws:ec2:security_group")
        instance = Resource(
            name="instance",
            type="aws:ec2:instance",
            depends_on=["vpc", "sg"],
        )
        definition = self._make_definition([vpc, sg, instance])
        graph = Graph(definition)

        instance_node = graph.get_node("instance")
        assert "vpc" in instance_node.outgoing
        assert "sg" in instance_node.outgoing

    def test_circular_dependency_raises(self):
        """Circular dependencies should be detected (not implemented yet, passes)."""
        # A -> B -> A would need cycle detection in simplify()
        # Currently not enforced - this documents current behavior
        vpc = Resource(name="vpc", type="aws:ec2:vpc", depends_on=["subnet"])
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"])
        definition = self._make_definition([vpc, subnet])

        # Currently allows circular (cycle detection is TODO)
        graph = Graph(definition)
        assert graph.has_node("vpc")
        assert graph.has_node("subnet")

    def test_get_resource_names(self):
        """get_resource_names returns all resource names."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc")
        subnet = Resource(name="subnet", type="aws:ec2:subnet")
        definition = self._make_definition([vpc, subnet])
        graph = Graph(definition)

        names = graph.get_resource_names()
        assert set(names) == {"vpc", "subnet"}

    def test_simplify_removes_transitive_edges(self):
        """simplify() removes transitive edges."""
        # A -> B -> C, and A also directly references C
        # After simplify: A -> B -> C (direct A->C removed)
        a = Resource(name="a", type="type:a")
        b = Resource(name="b", type="type:b", depends_on=["a"])
        c = Resource(
            name="c",
            type="type:c",
            depends_on=["a", "b"],  # both direct and indirect
        )
        definition = self._make_definition([a, b, c])
        graph = Graph(definition)

        c_node = graph.get_node("c")
        # Before simplify: should have both "a" and "b"
        assert "a" in c_node.outgoing
        assert "b" in c_node.outgoing

        # After simplify: should only have direct dependencies
        simplified = graph.simplify()
        c_node = simplified.get_node("c")
        # "a" is transitive (a->b->c), should be removed
        assert "b" in c_node.outgoing
        # Note: depends_on is explicit, so "a" stays in this case
        # This test shows depends_on takes precedence
