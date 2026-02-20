"""Tests for cold/planner.py"""
import pytest

from terra_py_form.cold.graph import Graph
from terra_py_form.cold.parser import InfraDefinition, Resource
from terra_py_form.cold.planner import Diff, Planner
from terra_py_form.cold.solver import Solver
from terra_py_form.cold.state import ResourceState, State


class TestPlanner:
    """Tests for Planner class."""

    def _make_graph(self, resources: list[Resource]) -> Graph:
        """Helper to create Graph from resources."""
        definition = InfraDefinition(version="1.0", variables={}, resources=resources)
        return Graph(definition)

    def _make_state(self, resources: dict[str, ResourceState]) -> State:
        """Helper to create State."""
        state = State()
        state.resources = resources
        return state

    def test_plan_create(self):
        """Resource not in state -> create diff."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        graph = self._make_graph([vpc])
        state = self._make_state({})

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        diff = diffs[0]
        assert diff.resource_name == "vpc"
        assert diff.action == "create"
        assert diff.before is None
        assert diff.after == {"cidr_block": "10.0.0.0/16"}
        assert diff.changes == {}

    def test_plan_update(self):
        """Resource exists with different properties -> update diff."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": True},
        )
        graph = self._make_graph([vpc])
        current_state = ResourceState(
            resource_type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": False},
        )
        state = self._make_state({"vpc": current_state})

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        diff = diffs[0]
        assert diff.action == "update"
        assert diff.changes == {"enable_dns_hostnames": (False, True)}

    def test_plan_noop(self):
        """Resource exists with same properties -> noop diff."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        graph = self._make_graph([vpc])
        current_state = ResourceState(
            resource_type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        state = self._make_state({"vpc": current_state})

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        diff = diffs[0]
        assert diff.action == "noop"
        assert diff.changes == {}

    def test_plan_removed_key(self):
        """Key removed from desired state -> update with None."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16"},  # no longer has enable_dns_hostnames
        )
        graph = self._make_graph([vpc])
        current_state = ResourceState(
            resource_type="aws:ec2:vpc",
            properties={"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": True},
        )
        state = self._make_state({"vpc": current_state})

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        diff = diffs[0]
        assert diff.action == "update"
        assert "enable_dns_hostnames" in diff.changes
        assert diff.changes["enable_dns_hostnames"] == (True, None)

    def test_plan_multiple_resources(self):
        """Plan for multiple resources."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", properties={"cidr_block": "10.0.0.0/16"})
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            properties={"vpc_id": "test"},
            depends_on=["vpc"],
        )
        graph = self._make_graph([vpc, subnet])
        state = self._make_state({})

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 2
        resource_names = [d.resource_name for d in diffs]
        assert set(resource_names) == {"vpc", "subnet"}

    def test_plan_with_order(self):
        """plan_with_order returns diffs in topological order."""
        vpc = Resource(name="vpc", type="aws:ec2:vpc", properties={"cidr_block": "10.0.0.0/16"})
        subnet = Resource(
            name="subnet",
            type="aws:ec2:subnet",
            properties={"vpc_id": "test"},
            depends_on=["vpc"],
        )
        graph = self._make_graph([vpc, subnet])
        state = self._make_state({})

        planner = Planner(state)
        diffs = planner.plan_with_order(graph)

        # vpc should come before subnet in the diff list
        vpc_idx = next(i for i, d in enumerate(diffs) if d.resource_name == "vpc")
        subnet_idx = next(i for i, d in enumerate(diffs) if d.resource_name == "subnet")
        assert vpc_idx < subnet_idx

    def test_plan_with_order_complex(self):
        """plan_with_order handles complex DAG."""
        #       vpc
        #      /   \
        #   subnet  sg
        #      \   /
        #      instance
        vpc = Resource(name="vpc", type="aws:ec2:vpc", properties={})
        subnet = Resource(name="subnet", type="aws:ec2:subnet", depends_on=["vpc"], properties={})
        sg = Resource(name="sg", type="aws:ec2:security_group", depends_on=["vpc"], properties={})
        instance = Resource(
            name="instance", type="aws:ec2:instance", depends_on=["subnet", "sg"], properties={}
        )
        graph = self._make_graph([vpc, subnet, sg, instance])
        state = self._make_state({})

        planner = Planner(state)
        diffs = planner.plan_with_order(graph)

        # Build position map
        positions = {d.resource_name: i for i, d in enumerate(diffs)}

        # vpc must come before subnet and sg
        assert positions["vpc"] < positions["subnet"]
        assert positions["vpc"] < positions["sg"]
        # subnet and sg must come before instance
        assert positions["subnet"] < positions["instance"]
        assert positions["sg"] < positions["instance"]

    def test_compute_diff_multiple_changes(self):
        """Multiple field changes tracked correctly."""
        vpc = Resource(
            name="vpc",
            type="aws:ec2:vpc",
            properties={
                "cidr_block": "10.0.0.0/16",
                "enable_dns_hostnames": True,
                "enable_dns_support": True,
            },
        )
        graph = self._make_graph([vpc])
        current_state = ResourceState(
            resource_type="aws:ec2:vpc",
            properties={
                "cidr_block": "172.16.0.0/12",
                "enable_dns_hostnames": False,
                "enable_dns_support": True,
            },
        )
        state = self._make_state({"vpc": current_state})

        planner = Planner(state)
        diffs = planner.plan(graph)

        diff = diffs[0]
        assert diff.action == "update"
        assert diff.changes["cidr_block"] == ("172.16.0.0/12", "10.0.0.0/16")
        assert diff.changes["enable_dns_hostnames"] == (False, True)
        # enable_dns_support is unchanged
        assert "enable_dns_support" not in diff.changes


class TestDiff:
    """Tests for Diff dataclass."""

    def test_diff_repr(self):
        """Diff has useful repr."""
        diff = Diff(resource_name="vpc", resource_type="aws:ec2:vpc", action="create")
        assert "vpc" in repr(diff)
        assert "create" in repr(diff)

    def test_diff_create_no_before(self):
        """Create diff has no before state."""
        diff = Diff(
            resource_name="vpc",
            resource_type="aws:ec2:vpc",
            action="create",
            before=None,
            after={"cidr": "10.0.0.0/16"},
        )
        assert diff.before is None
        assert diff.after == {"cidr": "10.0.0.0/16"}

    def test_diff_delete_no_after(self):
        """Delete diff has no after state."""
        diff = Diff(
            resource_name="vpc",
            resource_type="aws:ec2:vpc",
            action="delete",
            before={"cidr": "10.0.0.0/16"},
            after=None,
        )
        assert diff.before == {"cidr": "10.0.0.0/16"}
        assert diff.after is None

    def test_diff_changes_structure(self):
        """Changes dict has (old, new) tuples."""
        diff = Diff(
            resource_name="vpc",
            resource_type="aws:ec2:vpc",
            action="update",
            before={"count": 1},
            after={"count": 2},
            changes={"count": (1, 2)},
        )
        old_val, new_val = diff.changes["count"]
        assert old_val == 1
        assert new_val == 2
