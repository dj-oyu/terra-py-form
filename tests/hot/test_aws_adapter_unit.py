"""Additional tests for hot/adapters/aws.py"""
import pytest
from unittest.mock import MagicMock, patch

from terra_py_form.hot.adapters.aws import (
    AdapterResult,
    Adapter,
    EC2Adapter,
    S3Adapter,
    RDSAdapter,
    get_adapter,
)


class TestAdapterResult:
    """Tests for AdapterResult dataclass."""

    def test_adapter_result_success(self):
        """Successful result."""
        result = AdapterResult(success=True, resource_id="vpc-123")
        assert result.success is True
        assert result.resource_id == "vpc-123"
        assert result.error is None
        assert result.properties is None

    def test_adapter_result_failure(self):
        """Failed result with error."""
        result = AdapterResult(success=False, error="VPC not found")
        assert result.success is False
        assert result.error == "VPC not found"
        assert result.resource_id is None

    def test_adapter_result_with_properties(self):
        """Result with properties."""
        result = AdapterResult(
            success=True,
            resource_id="vpc-123",
            properties={"cidr_block": "10.0.0.0/16"},
        )
        assert result.properties["cidr_block"] == "10.0.0.0/16"


class TestAdapterInterface:
    """Tests for Adapter abstract class."""

    def test_adapter_is_abstract(self):
        """Adapter cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Adapter()


class TestEC2AdapterUnit:
    """Unit tests for EC2Adapter (without AWS)."""

    def test_ec2_adapter_init(self):
        """EC2Adapter initializes with region."""
        adapter = EC2Adapter(region="us-west-2")
        assert adapter.resource_type == "aws:ec2:*"

    def test_ec2_adapter_default_region(self):
        """EC2Adapter has default region."""
        adapter = EC2Adapter()
        assert adapter is not None

    def test_ec2_adapter_diff_added_key(self):
        """Diff detects added keys."""
        adapter = EC2Adapter()
        desired = {"cidr_block": "10.0.0.0/16", "new_field": "value"}
        actual = {"cidr_block": "10.0.0.0/16"}

        diff = adapter.diff(desired, actual)
        assert "new_field" in diff
        assert diff["new_field"] == (None, "value")

    def test_ec2_adapter_diff_removed_key(self):
        """Diff detects removed keys."""
        adapter = EC2Adapter()
        desired = {"cidr_block": "10.0.0.0/16"}
        actual = {"cidr_block": "10.0.0.0/16", "old_field": "value"}

        diff = adapter.diff(desired, actual)
        assert "old_field" in diff
        assert diff["old_field"] == ("value", None)

    def test_ec2_adapter_diff_no_changes(self):
        """Diff returns empty when identical."""
        adapter = EC2Adapter()
        desired = {"cidr_block": "10.0.0.0/16", "enable_dns": True}
        actual = {"cidr_block": "10.0.0.0/16", "enable_dns": True}

        diff = adapter.diff(desired, actual)
        assert diff == {}

    def test_ec2_adapter_diff_type_change(self):
        """Diff detects type changes."""
        adapter = EC2Adapter()
        desired = {"count": 2}
        actual = {"count": "2"}  # string vs int

        diff = adapter.diff(desired, actual)
        # Different types are considered different
        assert "count" in diff


class TestS3AdapterUnit:
    """Unit tests for S3Adapter (without AWS)."""

    def test_s3_adapter_init(self):
        """S3Adapter initializes with region."""
        adapter = S3Adapter(region="eu-west-1")
        assert adapter.resource_type == "aws:s3:*"

    def test_s3_adapter_create_requires_bucket_name(self):
        """S3Adapter create requires bucket name."""
        adapter = S3Adapter()
        result = adapter.create({})  # No bucket name

        assert result.success is False
        assert "Bucket name required" in result.error

    def test_s3_adapter_diff(self):
        """S3Adapter diff works."""
        adapter = S3Adapter()
        desired = {"bucket": "my-bucket", "acl": "private"}
        actual = {"bucket": "my-bucket", "acl": "public-read"}

        diff = adapter.diff(desired, actual)
        assert "acl" in diff


class TestRDSAdapterUnit:
    """Unit tests for RDSAdapter (without AWS)."""

    def test_rds_adapter_init(self):
        """RDSAdapter initializes with region."""
        adapter = RDSAdapter(region="ap-northeast-1")
        assert adapter.resource_type == "aws:rds:*"

    def test_rds_adapter_create_requires_identifier(self):
        """RDSAdapter create requires instance identifier."""
        adapter = RDSAdapter()
        result = adapter.create({})  # No identifier

        assert result.success is False
        assert "Instance identifier required" in result.error

    def test_rds_adapter_diff(self):
        """RDSAdapter diff works."""
        adapter = RDSAdapter()
        desired = {"instance_class": "db.t3.large"}
        actual = {"instance_class": "db.t3.micro"}

        diff = adapter.diff(desired, actual)
        assert "instance_class" in diff


class TestGetAdapterFactory:
    """Tests for get_adapter factory function."""

    def test_get_adapter_ec2_vpc(self):
        """get_adapter for VPC."""
        adapter = get_adapter("aws:ec2:vpc")
        assert isinstance(adapter, EC2Adapter)

    def test_get_adapter_ec2_subnet(self):
        """get_adapter for subnet."""
        adapter = get_adapter("aws:ec2:subnet")
        assert isinstance(adapter, EC2Adapter)

    def test_get_adapter_ec2_instance(self):
        """get_adapter for instance."""
        adapter = get_adapter("aws:ec2:instance")
        assert isinstance(adapter, EC2Adapter)

    def test_get_adapter_s3_bucket(self):
        """get_adapter for S3 bucket."""
        adapter = get_adapter("aws:s3:bucket")
        assert isinstance(adapter, S3Adapter)

    def test_get_adapter_s3_object(self):
        """get_adapter for S3 object."""
        adapter = get_adapter("aws:s3:object")
        assert isinstance(adapter, S3Adapter)

    def test_get_adapter_rds_instance(self):
        """get_adapter for RDS instance."""
        adapter = get_adapter("aws:rds:instance")
        assert isinstance(adapter, RDSAdapter)

    def test_get_adapter_rds_cluster(self):
        """get_adapter for RDS cluster."""
        adapter = get_adapter("aws:rds:cluster")
        assert isinstance(adapter, RDSAdapter)

    def test_get_adapter_with_region(self):
        """get_adapter passes region to adapter."""
        adapter = get_adapter("aws:ec2:vpc", region="ap-southeast-1")
        assert isinstance(adapter, EC2Adapter)

    def test_get_adapter_unknown_prefix(self):
        """get_adapter raises for unknown prefix."""
        with pytest.raises(ValueError, match="No adapter found"):
            get_adapter("azure:vm:virtual_machine")

    def test_get_adapter_unknown_type(self):
        """get_adapter raises for unknown type."""
        with pytest.raises(ValueError, match="No adapter found"):
            get_adapter("aws:lambda:function")
