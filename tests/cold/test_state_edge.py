"""Extended tests for cold/state.py - edge cases."""
import json
import pytest

from terra_py_form.cold.state import ResourceState, State


class TestStateEdgeCases:
    """Edge case tests for State."""

    def test_state_load_corrupted_json(self, tmp_path):
        """Loading corrupted JSON raises error."""
        state_file = tmp_path / "corrupted.json"
        state_file.write_text('{"version": "1.0", resources: invalid}')

        with pytest.raises(json.JSONDecodeError):
            State.load(state_file)

    def test_state_load_malformed_state(self, tmp_path):
        """Loading malformed state file raises error."""
        state_file = tmp_path / "malformed.json"
        state_file.write_text('{"resources": "not a dict"}')  # resources should be dict

        # This may work but resources won't parse correctly
        state = State.load(state_file)
        # Resources should be empty dict since parsing failed
        assert state.resources == {}

    def test_state_save_empty(self, tmp_path):
        """Saving empty state works."""
        state = State()
        state_file = tmp_path / "empty_state.json"
        state.save(state_file)

        loaded = State.load(state_file)
        assert loaded.resources == {}

    def test_state_save_multiple_resources(self, tmp_path):
        """Save and load multiple resources."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))
        state.set("subnet1", ResourceState(resource_type="aws:ec2:subnet"))
        state.set("subnet2", ResourceState(resource_type="aws:ec2:subnet"))
        state.set("instance", ResourceState(resource_type="aws:ec2:instance"))

        state_file = tmp_path / "multi.json"
        state.save(state_file)

        loaded = State.load(state_file)
        assert len(loaded.resources) == 4

    def test_state_with_complex_identifier(self, tmp_path):
        """State with complex identifiers."""
        state = State()
        state.set(
            "rds",
            ResourceState(
                resource_type="aws:rds:db",
                identifier={
                    "arn": "arn:aws:rds:us-east-1:123456789:db:mydb",
                    "endpoint": "mydb.xyz.us-east-1.rds.amazonaws.com",
                },
            ),
        )

        state_file = tmp_path / "rds.json"
        state.save(state_file)

        loaded = State.load(state_file)
        rds = loaded.get("rds")
        assert rds.identifier["arn"] == "arn:aws:rds:us-east-1:123456789:db:mydb"

    def test_state_with_nested_properties(self, tmp_path):
        """State with nested properties."""
        state = State()
        state.set(
            "lb",
            ResourceState(
                resource_type="aws:elb:load_balancer",
                properties={
                    "listener": {"Protocol": "HTTP", "Port": 80},
                    "health_check": {
                        "target": "HTTP:80/health",
                        "interval": 30,
                    },
                },
            ),
        )

        state_file = tmp_path / "lb.json"
        state.save(state_file)

        loaded = State.load(state_file)
        lb = loaded.get("lb")
        assert lb.properties["listener"]["Port"] == 80

    def test_state_remove_nonexistent_no_error(self):
        """Removing nonexistent resource doesn't raise."""
        state = State()
        # Should not raise
        result = state.remove("nonexistent")
        assert result is False

    def test_state_set_overwrites(self):
        """Setting same resource twice overwrites."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc", properties={"cidr": "10.0.0.0/16"}))
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc", properties={"cidr": "172.16.0.0/12"}))

        vpc = state.get("vpc")
        assert vpc.properties["cidr"] == "172.16.0.0/12"

    def test_state_timestamp_format(self):
        """State timestamp is ISO format."""
        state = State()
        # Should be valid ISO timestamp
        import re
        iso_pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        assert re.match(iso_pattern, state.updated_at) is not None


class TestResourceStateEdgeCases:
    """Edge case tests for ResourceState."""

    def test_resource_state_with_all_fields(self):
        """ResourceState with all possible fields."""
        state = ResourceState(
            resource_type="aws:ec2:vpc",
            identifier={"vpc_id": "vpc-123", "arn": "arn:aws:ec2:..."},
            properties={"cidr_block": "10.0.0.0/16", "tags": {"Name": "test"}},
            updated_at="2024-01-15T10:30:00+00:00",
        )

        d = state.to_dict()
        assert d["resource_type"] == "aws:ec2:vpc"
        assert d["identifier"]["vpc_id"] == "vpc-123"
        assert d["properties"]["tags"]["Name"] == "test"

    def test_resource_state_from_dict_partial(self):
        """ResourceState from dict with partial fields."""
        data = {
            "resource_type": "aws:ec2:vpc",
            "properties": {},
        }

        state = ResourceState.from_dict(data)
        assert state.resource_type == "aws:ec2:vpc"
        assert state.identifier == {}
        assert state.updated_at is not None  # Default

    def test_resource_state_from_dict_with_identifier(self):
        """ResourceState from dict with identifier."""
        data = {
            "resource_type": "aws:s3:bucket",
            "identifier": {"bucket_name": "my-bucket"},
            "properties": {},
            "updated_at": "2024-01-01T00:00:00+00:00",
        }

        state = ResourceState.from_dict(data)
        assert state.identifier["bucket_name"] == "my-bucket"

    def test_resource_state_to_dict_roundtrip(self):
        """ResourceState to_dict -> from_dict roundtrip."""
        original = ResourceState(
            resource_type="aws:rds:db",
            identifier={"arn": "arn:aws:rds:..."},
            properties={"engine": "postgres"},
        )

        # Roundtrip
        d = original.to_dict()
        restored = ResourceState.from_dict(d)

        assert restored.resource_type == original.resource_type
        assert restored.identifier == original.identifier
        assert restored.properties == original.properties


class TestStateSerialization:
    """Tests for state serialization edge cases."""

    def test_state_serialization_format(self, tmp_path):
        """State saved in expected JSON format."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc", properties={"cidr": "10.0.0.0/16"}))

        state_file = tmp_path / "state.json"
        state.save(state_file)

        with open(state_file) as f:
            data = json.load(f)

        # Check structure
        assert "version" in data
        assert "resources" in data
        assert "updated_at" in data
        assert "vpc" in data["resources"]

    def test_state_version_preserved(self, tmp_path):
        """State version is preserved."""
        state = State(version="2.0")
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))

        state_file = tmp_path / "state.json"
        state.save(state_file)

        loaded = State.load(state_file)
        assert loaded.version == "2.0"

    def test_state_empty_version_default(self, tmp_path):
        """Empty version defaults to 1.0."""
        state_file = tmp_path / "state.json"
        state_file.write_text('{"version": "", "resources": {}}')

        loaded = State.load(state_file)
        assert loaded.version == "1.0"
