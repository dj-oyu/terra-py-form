"""Integration tests - full workflow from parse to diff."""
import pytest

from terra_py_form.cold.graph import Graph
from terra_py_form.cold.parser import Parser
from terra_py_form.cold.planner import Planner, Diff
from terra_py_form.cold.solver import Solver
from terra_py_form.cold.state import ResourceState, State


class TestParsePlanDiffWorkflow:
    """Full workflow: Parse YAML -> Build Graph -> Plan -> Diff."""

    def test_simple_workflow(self):
        """Simple workflow: create new VPC."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16
"""
        # 1. Parse
        parser = Parser()
        definition = parser.parse_string(yaml_content)

        # 2. Build Graph
        graph = Graph(definition)

        # 3. Plan (empty state = all creates)
        state = State()
        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        assert diffs[0].action == "create"
        assert diffs[0].resource_name == "vpc"

    def test_workflow_with_dependencies(self):
        """Workflow with dependencies."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16

  subnet:
    type: aws:ec2:subnet
    depends_on:
      - vpc
    properties:
      vpc_id: ${ref(vpc)}
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        # Check topological order
        solver = Solver(graph)
        order = solver.topological_sort()

        assert order.index("vpc") < order.index("subnet")

    def test_workflow_update_existing(self):
        """Workflow: update existing resource."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16
      enable_dns_hostnames: true
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        # Create existing state
        state = State()
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={
                    "cidr_block": "10.0.0.0/16",
                    "enable_dns_hostnames": False,
                },
            ),
        )

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        assert diffs[0].action == "update"
        assert "enable_dns_hostnames" in diffs[0].changes

    def test_workflow_noop(self):
        """Workflow: resource unchanged."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        # Exact same state
        state = State()
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={"cidr_block": "10.0.0.0/16"},
            ),
        )

        planner = Planner(state)
        diffs = planner.plan(graph)

        assert len(diffs) == 1
        assert diffs[0].action == "noop"

    def test_workflow_delete_removed(self):
        """Workflow: resource removed from desired state."""
        yaml_content = """
resources:
  subnet:
    type: aws:ec2:subnet
    properties:
      vpc_id: vpc-123
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        # State has more resources than desired
        state = State()
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={"cidr_block": "10.0.0.0/16"},
            ),
        )
        state.set(
            "subnet",
            ResourceState(
                resource_type="aws:ec2:subnet",
                properties={"vpc_id": "vpc-123"},
            ),
        )

        planner = Planner(state)
        diffs = planner.plan(graph)

        # vpc: delete (in state but not in graph)
        # subnet: noop (in both, same properties)
        assert len(diffs) == 2

        vpc_diff = next(d for d in diffs if d.resource_name == "vpc")
        subnet_diff = next(d for d in diffs if d.resource_name == "subnet")

        assert vpc_diff.action == "delete"
        assert subnet_diff.action == "noop"


class TestComplexWorkflows:
    """Complex workflow scenarios."""

    def test_multi_resource_dag(self):
        """Complex DAG with multiple paths."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16

  subnet_a:
    type: aws:ec2:subnet
    depends_on: vpc
    properties:
      availability_zone: us-east-1a

  subnet_b:
    type: aws:ec2:subnet
    depends_on: vpc
    properties:
      availability_zone: us-east-1b

  sg:
    type: aws:ec2:security_group
    depends_on: vpc
    properties:
      name: web-sg

  instance:
    type: aws:ec2:instance
    depends_on:
      - subnet_a
      - subnet_b
      - sg
    properties:
      instance_type: t3.micro
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        solver = Solver(graph)
        order = solver.topological_sort()

        # Check dependencies
        assert order.index("vpc") < order.index("subnet_a")
        assert order.index("vpc") < order.index("subnet_b")
        assert order.index("vpc") < order.index("sg")
        assert order.index("subnet_a") < order.index("instance")
        assert order.index("subnet_b") < order.index("instance")
        assert order.index("sg") < order.index("instance")

    def test_workflow_with_variables(self):
        """Workflow with variable substitution."""
        yaml_content = """
version: "2.0"
variables:
  cidr: 172.16.0.0/12
  env: prod

resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: ${var.cidr}
      tags:
        Environment: ${var.env}
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)

        assert definition.variables["cidr"] == "172.16.0.0/12"
        assert definition.variables["env"] == "prod"

        # Variables are not substituted in properties (that's a runtime concern)
        vpc = definition.resources[0]
        assert "${var.cidr}" in vpc.properties["cidr_block"]

    def test_workflow_with_refs(self):
        """Workflow with cross-resource references."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16

  subnet:
    type: aws:ec2:subnet
    properties:
      vpc_id: ${ref(vpc)}
      cidr: ${ref(vpc.id)}
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)

        # Parser extracts references
        subnet = next(r for r in definition.resources if r.name == "subnet")
        assert "vpc" in subnet.source_refs

        # Graph builds edges from refs
        graph = Graph(definition)
        solver = Solver(graph)
        order = solver.topological_sort()

        assert order.index("vpc") < order.index("subnet")

    def test_empty_workflow(self):
        """Empty YAML workflow."""
        yaml_content = """
resources: {}
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        state = State()
        planner = Planner(state)
        diffs = planner.plan(graph)

        assert diffs == []


class TestPlannerWithState:
    """Planner behavior with various state scenarios."""

    def test_plan_with_partial_state(self):
        """Plan when only some resources exist in state."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16

  subnet:
    type: aws:ec2:subnet
    properties:
      vpc_id: vpc-123
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        # Only VPC exists in state
        state = State()
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={"cidr_block": "10.0.0.0/16"},
            ),
        )

        planner = Planner(state)
        diffs = planner.plan(graph)

        # VPC is noop, subnet is create
        vpc_diff = next(d for d in diffs if d.resource_name == "vpc")
        subnet_diff = next(d for d in diffs if d.resource_name == "subnet")

        assert vpc_diff.action == "noop"
        assert subnet_diff.action == "create"

    def test_plan_detects_multiple_changes(self):
        """Plan detects multiple field changes."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 172.16.0.0/12
      enable_dns_hostnames: true
      enable_dns_support: true
"""
        parser = Parser()
        definition = parser.parse_string(yaml_content)
        graph = Graph(definition)

        state = State()
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={
                    "cidr_block": "10.0.0.0/16",
                    "enable_dns_hostnames": False,
                    "enable_dns_support": False,
                },
            ),
        )

        planner = Planner(state)
        diffs = planner.plan(graph)

        diff = diffs[0]
        assert diff.action == "update"
        assert len(diff.changes) == 3  # All three fields changed
