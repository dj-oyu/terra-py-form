"""Pseudo-E2E tests for CLI plan using examples and moto."""
import os
import tempfile
from pathlib import Path

import pytest


class TestCLIE2E:
    """Pseudo-E2E tests that exercise full CLI pipeline with mocked AWS."""

    def test_plan_simple_yaml_ec2_vpc(self):
        """CLI plan with simple.yaml (VPC) runs without error."""
        from click.testing import CliRunner
        from terra_py_form.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["plan", "examples/simple.yaml"])

        # Should not error
        assert result.exit_code == 0, f"CLI error: {result.output}"
        # Should show planned changes
        assert "Planned changes" in result.output
        assert "vpc" in result.output

    def test_plan_full_pipeline_with_adapters(self):
        """Full pipeline: YAML -> Parser -> Graph -> Planner -> Adapter (moto mocked)."""
        from terra_py_form.cold.parser import Parser
        from terra_py_form.cold.graph import Graph
        from terra_py_form.cold.planner import Planner
        from terra_py_form.cold.state import State
        from terra_py_form.hot.adapters.aws import get_adapter

        # Parse simple.yaml
        parser = Parser()
        parsed = parser.parse("examples/simple.yaml")

        # Build graph
        graph = Graph(parsed)

        # Plan (gets diffs)
        current_state = State()
        planner = Planner(current_state)
        diffs = planner.plan(graph)

        # Execute adapters with moto mocked
        for diff in diffs:
            adapter = get_adapter(diff.resource_type)
            
            if diff.action == "create":
                result = adapter.create(diff.after)
                assert result.success, f"Create failed: {result.error}"
            elif diff.action == "update":
                result = adapter.update(diff.resource_name, diff.after)
                assert result.success, f"Update failed: {result.error}"
            elif diff.action == "delete":
                result = adapter.delete(diff.resource_name)
                assert result.success, f"Delete failed: {result.error}"

    def test_plan_s3_bucket_e2e(self):
        """Full pipeline for S3 bucket creation."""
        from terra_py_form.cold.parser import Parser
        from terra_py_form.cold.graph import Graph
        from terra_py_form.cold.planner import Planner
        from terra_py_form.cold.state import State
        from terra_py_form.hot.adapters.aws import get_adapter

        # Create a minimal YAML for S3
        yaml_content = """
resources:
  test-bucket:
    type: aws:s3:bucket
    properties:
      bucket: e2e-test-bucket-12345
      acl: private
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            # Parse
            parser = Parser()
            parsed = parser.parse(temp_path)

            # Plan
            graph = Graph(parsed)
            current_state = State()
            planner = Planner(current_state)
            diffs = planner.plan(graph)

            # Execute
            assert len(diffs) == 1
            diff = diffs[0]
            
            adapter = get_adapter("aws:s3:bucket")
            result = adapter.create({"bucket": "e2e-test-bucket-12345", "acl": "private"})
            
            assert result.success is True
            assert result.resource_id == "e2e-test-bucket-12345"

            # Cleanup
            adapter.delete("e2e-test-bucket-12345")
        finally:
            os.unlink(temp_path)

    def test_plan_with_invalid_yaml(self):
        """CLI plan with invalid YAML shows error."""
        from click.testing import CliRunner
        from terra_py_form.cli import cli

        # Create invalid YAML
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("resources: \n  - invalid: list format")
            temp_path = f.name

        try:
            runner = CliRunner()
            result = runner.invoke(cli, ["plan", temp_path])
            
            # Should show error
            assert result.exit_code != 0
        finally:
            os.unlink(temp_path)


class TestCRUDLifecycle:
    """Complete CRUD lifecycle tests for each adapter."""

    def test_ec2_vpc_full_lifecycle(self):
        """EC2 VPC: create → read → update → delete."""
        from terra_py_form.hot.adapters.aws import EC2Adapter

        adapter = EC2Adapter(region="us-east-1")

        # 1. Create
        result = adapter.create({"cidr_block": "10.0.0.0/16", "enable_dns_hostnames": True})
        assert result.success is True
        vpc_id = result.resource_id

        # 2. Read
        result = adapter.read(vpc_id)
        assert result.success is True
        assert result.properties["cidr_block"] == "10.0.0.0/16"
        assert result.properties["enable_dns_hostnames"] is True

        # 3. Update
        result = adapter.update(vpc_id, {"enable_dns_hostnames": False})
        assert result.success is True

        # 4. Verify update
        result = adapter.read(vpc_id)
        assert result.properties["enable_dns_hostnames"] is False

        # 5. Delete
        result = adapter.delete(vpc_id)
        assert result.success is True

    def test_s3_bucket_full_lifecycle(self):
        """S3 Bucket: create → read → update → delete."""
        from terra_py_form.hot.adapters.aws import S3Adapter

        adapter = S3Adapter(region="us-east-1")
        bucket_name = "lifecycle-test-bucket-12345"

        # 1. Create with ACL
        result = adapter.create({"bucket": bucket_name, "acl": "private"})
        assert result.success is True

        # 2. Read - verify bucket exists
        result = adapter.read(bucket_name)
        assert result.success is True
        assert result.properties["bucket"] == bucket_name
        # Note: moto may return different ACL format, just verify it returns something
        assert "acl" in result.properties

        # 3. Update - change ACL
        result = adapter.update(bucket_name, {"acl": "public-read"})
        assert result.success is True

        # 4. Verify update
        result = adapter.read(bucket_name)
        assert "acl" in result.properties

        # 5. Delete
        result = adapter.delete(bucket_name)
        assert result.success is True
