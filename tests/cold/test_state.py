"""Tests for cold/state.py"""
import json
import pytest

from terra_py_form.cold.state import ResourceState, State


class TestResourceState:
    """Tests for ResourceState dataclass."""

    def test_resource_state_defaults(self):
        """ResourceState has sensible defaults."""
        state = ResourceState(resource_type="aws:ec2:vpc")

        assert state.identifier == {}
        assert state.properties == {}
        assert state.updated_at is not None

    def test_resource_state_full(self):
        """ResourceState accepts all fields."""
        state = ResourceState(
            resource_type="aws:ec2:vpc",
            identifier={"arn": "arn:aws:ec2:us-east-1:123456789:vpc/vpc-123"},
            properties={"cidr_block": "10.0.0.0/16"},
            updated_at="2024-01-01T00:00:00+00:00",
        )

        assert state.identifier["arn"] == "arn:aws:ec2:us-east-1:123456789:vpc/vpc-123"
        assert state.properties["cidr_block"] == "10.0.0.0/16"

    def test_resource_state_to_dict(self):
        """ResourceState serializes to dict."""
        state = ResourceState(
            resource_type="aws:ec2:vpc",
            identifier={"id": "vpc-123"},
            properties={"foo": "bar"},
        )

        d = state.to_dict()
        assert d["resource_type"] == "aws:ec2:vpc"
        assert d["identifier"]["id"] == "vpc-123"
        assert d["properties"]["foo"] == "bar"

    def test_resource_state_from_dict(self):
        """ResourceState deserializes from dict."""
        data = {
            "resource_type": "aws:ec2:vpc",
            "identifier": {"id": "vpc-123"},
            "properties": {"cidr": "10.0.0.0/16"},
            "updated_at": "2024-01-01T00:00:00+00:00",
        }

        state = ResourceState.from_dict(data)
        assert state.resource_type == "aws:ec2:vpc"
        assert state.identifier["id"] == "vpc-123"


class TestState:
    """Tests for State class."""

    def test_empty_state(self):
        """Empty state has no resources."""
        state = State()

        assert state.version == "1.0"
        assert state.resources == {}
        assert state.updated_at is not None

    def test_state_get_missing(self):
        """Getting missing resource returns None."""
        state = State()

        assert state.get("nonexistent") is None

    def test_state_set_and_get(self):
        """Can set and get resource state."""
        state = State()
        res_state = ResourceState(
            resource_type="aws:ec2:vpc",
            identifier={"id": "vpc-123"},
            properties={"cidr_block": "10.0.0.0/16"},
        )

        state.set("my_vpc", res_state)

        retrieved = state.get("my_vpc")
        assert retrieved is not None
        assert retrieved.resource_type == "aws:ec2:vpc"
        assert retrieved.identifier["id"] == "vpc-123"

    def test_state_remove_existing(self):
        """Removing existing resource returns True."""
        state = State()
        res_state = ResourceState(resource_type="aws:ec2:vpc")
        state.set("vpc", res_state)

        result = state.remove("vpc")

        assert result is True
        assert state.get("vpc") is None

    def test_state_remove_missing(self):
        """Removing missing resource returns False."""
        state = State()

        result = state.remove("nonexistent")

        assert result is False

    def test_state_clear(self):
        """Clear removes all resources."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))
        state.set("subnet", ResourceState(resource_type="aws:ec2:subnet"))

        state.clear()

        assert len(state.resources) == 0
        assert state.get("vpc") is None
        assert state.get("subnet") is None

    def test_state_save_and_load(self, tmp_path):
        """State can be saved to and loaded from file."""
        state = State()
        state.set(
            "my_vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                identifier={"id": "vpc-123"},
                properties={"cidr_block": "10.0.0.0/16"},
            ),
        )

        state_file = tmp_path / "state.json"
        state.save(state_file)

        # Verify file content
        with open(state_file) as f:
            data = json.load(f)

        assert data["version"] == "1.0"
        assert "my_vpc" in data["resources"]
        assert data["resources"]["my_vpc"]["resource_type"] == "aws:ec2:vpc"

        # Load back
        loaded = State.load(state_file)

        assert loaded.get("my_vpc") is not None
        assert loaded.get("my_vpc").identifier["id"] == "vpc-123"

    def test_state_load_nonexistent(self, tmp_path):
        """Loading nonexistent file returns empty state."""
        state_file = tmp_path / "nonexistent.json"

        loaded = State.load(state_file)

        assert loaded.version == "1.0"
        assert loaded.resources == {}

    def test_state_save_creates_parent_dirs(self, tmp_path):
        """Save creates parent directories."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))

        state_file = tmp_path / "deep" / "nested" / "state.json"
        state.save(state_file)

        assert state_file.exists()

    def test_state_updates_timestamp_on_change(self):
        """State updates timestamp when resources change."""
        state = State()
        original_updated_at = state.updated_at

        # Small delay to ensure different timestamp
        import time
        time.sleep(0.01)

        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))

        assert state.updated_at != original_updated_at

    def test_state_updates_timestamp_on_remove(self):
        """State updates timestamp when resource removed."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))
        original_updated_at = state.updated_at

        import time
        time.sleep(0.01)

        state.remove("vpc")

        assert state.updated_at != original_updated_at

    def test_state_multiple_resources(self):
        """State can hold multiple resources."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))
        state.set("subnet", ResourceState(resource_type="aws:ec2:subnet"))
        state.set("instance", ResourceState(resource_type="aws:ec2:instance"))

        assert len(state.resources) == 3
        assert state.get("vpc") is not None
        assert state.get("subnet") is not None
        assert state.get("instance") is not None

    def test_state_overwrite_resource(self):
        """Setting existing resource overwrites it."""
        state = State()
        state.set("vpc", ResourceState(resource_type="aws:ec2:vpc"))
        state.set(
            "vpc",
            ResourceState(
                resource_type="aws:ec2:vpc",
                properties={"cidr_block": "10.0.0.0/16"},
            ),
        )

        assert len(state.resources) == 1
        assert state.get("vpc").properties["cidr_block"] == "10.0.0.0/16"
