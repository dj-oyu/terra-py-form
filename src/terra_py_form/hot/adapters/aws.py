"""AWS resource adapters for hot deployment."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class AdapterResult:
    """Result of an adapter operation."""

    success: bool
    resource_id: str | None = None  # AWS resource ID (vpc-id, bucket-name, etc.)
    properties: dict[str, Any] | None = None  # Current state
    error: str | None = None


class Adapter(ABC):
    """Abstract base class for AWS resource adapters."""

    resource_type: str = ""

    @abstractmethod
    def create(self, properties: dict[str, Any]) -> AdapterResult:
        """Create an AWS resource."""
        pass

    @abstractmethod
    def read(self, resource_id: str) -> AdapterResult:
        """Read an AWS resource's current state."""
        pass

    @abstractmethod
    def update(self, resource_id: str, properties: dict[str, Any]) -> AdapterResult:
        """Update an AWS resource."""
        pass

    @abstractmethod
    def delete(self, resource_id: str) -> AdapterResult:
        """Delete an AWS resource."""
        pass

    @abstractmethod
    def diff(self, desired: dict[str, Any], actual: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Compute diff between desired and actual state."""
        pass


class EC2Adapter(Adapter):
    """Adapter for EC2 resources."""

    resource_type = "aws:ec2:*"

    def __init__(self, region: str = "us-east-1"):
        """Initialize EC2 adapter with boto3 client."""
        import boto3

        self.client = boto3.client("ec2", region_name=region)

    def create(self, properties: dict[str, Any]) -> AdapterResult:
        """Create an EC2 VPC."""
        try:
            # Extract VPC properties
            cidr_block = properties.get("cidr_block", "10.0.0.0/16")
            vpc_kwargs = {"CidrBlock": cidr_block}

            if "instance_tenancy" in properties:
                vpc_kwargs["InstanceTenancy"] = properties["instance_tenancy"]

            if "amazon_side_asn" in properties:
                vpc_kwargs["AmazonSideAsn"] = properties["amazon_side_asn"]

            response = self.client.create_vpc(**vpc_kwargs)
            vpc_id = response["Vpc"]["VpcId"]

            # Handle optional enable_dns_hostnames
            if properties.get("enable_dns_hostnames"):
                self.client.modify_vpc_attribute(
                    VpcId=vpc_id,
                    EnableDnsHostnames={"Value": True},
                )

            # Handle optional enable_dns_support
            if properties.get("enable_dns_support"):
                self.client.modify_vpc_attribute(
                    VpcId=vpc_id,
                    EnableDnsSupport={"Value": True},
                )

            # Wait for VPC to be available
            waiter = self.client.get_waiter("vpc_available")
            waiter.wait(VpcIds=[vpc_id])

            return AdapterResult(success=True, resource_id=vpc_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def read(self, resource_id: str) -> AdapterResult:
        """Read an EC2 VPC."""
        try:
            response = self.client.describe_vpcs(VpcIds=[resource_id])
            if not response["Vpcs"]:
                return AdapterResult(success=False, error="VPC not found")

            vpc = response["Vpcs"][0]

            # Get attributes
            dns_support = self.client.describe_vpc_attribute(
                VpcId=resource_id, Attribute="enableDnsSupport"
            )
            dns_hostnames = self.client.describe_vpc_attribute(
                VpcId=resource_id, Attribute="enableDnsHostnames"
            )

            properties = {
                "cidr_block": vpc["CidrBlock"],
                "instance_tenancy": vpc["InstanceTenancy"],
                "enable_dns_support": dns_support["EnableDnsSupport"]["Value"],
                "enable_dns_hostnames": dns_hostnames["EnableDnsHostnames"]["Value"],
            }

            return AdapterResult(success=True, resource_id=resource_id, properties=properties)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def update(self, resource_id: str, properties: dict[str, Any]) -> AdapterResult:
        """Update an EC2 VPC."""
        try:
            if "enable_dns_hostnames" in properties:
                self.client.modify_vpc_attribute(
                    VpcId=resource_id,
                    EnableDnsHostnames={"Value": properties["enable_dns_hostnames"]},
                )

            if "enable_dns_support" in properties:
                self.client.modify_vpc_attribute(
                    VpcId=resource_id,
                    EnableDnsSupport={"Value": properties["enable_dns_support"]},
                )

            # Note: CIDR block cannot be changed after creation
            # Note: Instance tenancy cannot be changed after creation

            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def delete(self, resource_id: str) -> AdapterResult:
        """Delete an EC2 VPC."""
        try:
            self.client.delete_vpc(VpcId=resource_id)

            # Wait for VPC to be deleted (moto may not support all waiters)
            try:
                waiter = self.client.get_waiter("vpc_deleted")
                waiter.wait(VpcIds=[resource_id])
            except Exception:
                # Moto may not support vpc_deleted waiter, just verify deletion
                import time
                for _ in range(10):
                    try:
                        self.client.describe_vpcs(VpcIds=[resource_id])
                        time.sleep(0.5)
                    except Exception:
                        # VPC not found = deleted successfully
                        break

            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def diff(self, desired: dict[str, Any], actual: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Compute diff between desired and actual VPC state."""
        changes = {}

        # Check each desired key
        for key, desired_value in desired.items():
            actual_value = actual.get(key)
            if actual_value != desired_value:
                changes[key] = (actual_value, desired_value)

        # Check for removed keys
        for key in actual:
            if key not in desired:
                changes[key] = (actual[key], None)

        return changes


class S3Adapter(Adapter):
    """Adapter for S3 resources."""

    resource_type = "aws:s3:*"

    def __init__(self, region: str = "us-east-1"):
        """Initialize S3 adapter with boto3 client."""
        import boto3

        self.client = boto3.client("s3", region_name=region)

    def create(self, properties: dict[str, Any]) -> AdapterResult:
        """Create an S3 bucket."""
        try:
            bucket_name = properties.get("bucket")
            if not bucket_name:
                return AdapterResult(success=False, error="Bucket name required")

            # Create bucket
            if properties.get("region", "us-east-1") != "us-east-1":
                self.client.create_bucket(
                    Bucket=bucket_name,
                    CreateBucketConfiguration={
                        "LocationConstraint": properties["region"]
                    },
                )
            else:
                self.client.create_bucket(Bucket=bucket_name)

            # Set ACL if specified
            if "acl" in properties:
                self.client.put_bucket_acl(Bucket=bucket_name, ACL=properties["acl"])

            # Set versioning if specified
            if "versioning" in properties:
                self.client.put_bucket_versioning(
                    Bucket=bucket_name,
                    VersioningConfiguration={
                        "Status": "Enabled" if properties["versioning"] else "Suspended"
                    },
                )

            return AdapterResult(success=True, resource_id=bucket_name)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def read(self, resource_id: str) -> AdapterResult:
        """Read an S3 bucket."""
        try:
            # Get bucket location (works even if bucket is empty)
            try:
                location_response = self.client.get_bucket_location(Bucket=resource_id)
                region = location_response["LocationConstraint"] or "us-east-1"
            except Exception:
                region = "us-east-1"

            # Get ACL
            acl_response = self.client.get_bucket_acl(Bucket=resource_id)
            acl = acl_response["Grants"][0]["Permission"] if acl_response.get("Grants") else "private"

            # Get versioning
            try:
                versioning_response = self.client.get_bucket_versioning(Bucket=resource_id)
                versioning = versioning_response.get("Status") == "Enabled"
            except Exception:
                versioning = False

            properties = {
                "bucket": resource_id,
                "region": region,
                "acl": acl,
                "versioning": versioning,
            }

            return AdapterResult(success=True, resource_id=resource_id, properties=properties)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def update(self, resource_id: str, properties: dict[str, Any]) -> AdapterResult:
        """Update an S3 bucket."""
        try:
            if "acl" in properties:
                self.client.put_bucket_acl(Bucket=resource_id, ACL=properties["acl"])

            if "versioning" in properties:
                self.client.put_bucket_versioning(
                    Bucket=resource_id,
                    VersioningConfiguration={
                        "Status": "Enabled" if properties["versioning"] else "Suspended"
                    },
                )

            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def delete(self, resource_id: str) -> AdapterResult:
        """Delete an S3 bucket."""
        try:
            self.client.delete_bucket(Bucket=resource_id)
            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def diff(self, desired: dict[str, Any], actual: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Compute diff between desired and actual S3 bucket state."""
        changes = {}

        for key, desired_value in desired.items():
            actual_value = actual.get(key)
            if actual_value != desired_value:
                changes[key] = (actual_value, desired_value)

        for key in actual:
            if key not in desired:
                changes[key] = (actual[key], None)

        return changes


class RDSAdapter(Adapter):
    """Adapter for RDS resources."""

    resource_type = "aws:rds:*"

    def __init__(self, region: str = "us-east-1"):
        """Initialize RDS adapter with boto3 client."""
        import boto3

        self.client = boto3.client("rds", region_name=region)

    def create(self, properties: dict[str, Any]) -> AdapterResult:
        """Create an RDS instance."""
        try:
            db_instance_identifier = properties.get("instance_identifier")
            if not db_instance_identifier:
                return AdapterResult(success=False, error="Instance identifier required")

            db_kwargs = {
                "DBInstanceIdentifier": db_instance_identifier,
                "Engine": properties.get("engine", "postgres"),
                "DBInstanceClass": properties.get("instance_class", "db.t3.micro"),
                "AllocatedStorage": properties.get("allocated_storage", 20),
                "MasterUsername": properties.get("master_username", "admin"),
                "MasterUserPassword": properties.get("master_password"),
            }

            if "vpc_security_group_ids" in properties:
                db_kwargs["VpcSecurityGroupIds"] = properties["vpc_security_group_ids"]

            if "db_name" in properties:
                db_kwargs["DBName"] = properties["db_name"]

            if "multi_az" in properties:
                db_kwargs["MultiAZ"] = properties["multi_az"]

            response = self.client.create_db_instance(**db_kwargs)
            db_instance = response["DBInstance"]
            db_instance_arn = db_instance["DBInstanceArn"]

            # Wait for available
            waiter = self.client.get_waiter("db_instance_available")
            waiter.wait(DBInstanceIdentifier=db_instance_identifier)

            return AdapterResult(success=True, resource_id=db_instance_arn)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def read(self, resource_id: str) -> AdapterResult:
        """Read an RDS instance."""
        try:
            # Extract DBInstanceIdentifier from ARN if needed
            db_instance_identifier = resource_id
            if ":" in resource_id:
                # ARN format: arn:aws:rds:region:account:db:instance-identifier
                db_instance_identifier = resource_id.split(":")[-1]

            response = self.client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier)
            if not response["DBInstances"]:
                return AdapterResult(success=False, error="DB instance not found")

            db = response["DBInstances"][0]

            properties = {
                "instance_identifier": db["DBInstanceIdentifier"],
                "engine": db["Engine"],
                "engine_version": db["EngineVersion"],
                "instance_class": db["DBInstanceClass"],
                "allocated_storage": db["AllocatedStorage"],
                "db_name": db.get("DBName"),
                "multi_az": db["MultiAZ"],
                "status": db["DBInstanceStatus"],
            }

            return AdapterResult(success=True, resource_id=resource_id, properties=properties)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def update(self, resource_id: str, properties: dict[str, Any]) -> AdapterResult:
        """Update an RDS instance."""
        try:
            db_instance_identifier = resource_id
            if ":" in resource_id:
                db_instance_identifier = resource_id.split(":")[-1]

            update_kwargs = {}

            if "instance_class" in properties:
                update_kwargs["DBInstanceClass"] = properties["instance_class"]

            if "allocated_storage" in properties:
                update_kwargs["AllocatedStorage"] = properties["allocated_storage"]

            if "master_user_password" in properties:
                update_kwargs["MasterUserPassword"] = properties["master_user_password"]

            if "multi_az" in properties:
                update_kwargs["MultiAZ"] = properties["multi_az"]

            if update_kwargs:
                update_kwargs["DBInstanceIdentifier"] = db_instance_identifier
                self.client.modify_db_instance(**update_kwargs)

                # Wait for modifications to complete
                waiter = self.client.get_waiter("db_instance_available")
                waiter.wait(DBInstanceIdentifier=db_instance_identifier)

            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def delete(self, resource_id: str) -> AdapterResult:
        """Delete an RDS instance."""
        try:
            db_instance_identifier = resource_id
            if ":" in resource_id:
                db_instance_identifier = resource_id.split(":")[-1]

            self.client.delete_db_instance(
                DBInstanceIdentifier=db_instance_identifier,
                SkipFinalSnapshot=True,
            )

            # Wait for deleted
            waiter = self.client.get_waiter("db_instance_deleted")
            waiter.wait(DBInstanceIdentifier=db_instance_identifier)

            return AdapterResult(success=True, resource_id=resource_id)

        except Exception as e:
            return AdapterResult(success=False, error=str(e))

    def diff(self, desired: dict[str, Any], actual: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Compute diff between desired and actual RDS instance state."""
        changes = {}

        for key, desired_value in desired.items():
            actual_value = actual.get(key)
            if actual_value != desired_value:
                changes[key] = (actual_value, desired_value)

        for key in actual:
            if key not in desired:
                changes[key] = (actual[key], None)

        return changes


def get_adapter(resource_type: str, region: str = "us-east-1") -> Adapter:
    """Factory function to get the appropriate adapter for a resource type.

    Args:
        resource_type: The resource type (e.g., "aws:ec2:vpc", "aws:s3:bucket")
        region: AWS region

    Returns:
        Appropriate Adapter instance

    Raises:
        ValueError: If no adapter found for the resource type
    """
    if resource_type.startswith("aws:ec2:"):
        return EC2Adapter(region)
    elif resource_type.startswith("aws:s3:"):
        return S3Adapter(region)
    elif resource_type.startswith("aws:rds:"):
        return RDSAdapter(region)
    else:
        raise ValueError(f"No adapter found for resource type: {resource_type}")
