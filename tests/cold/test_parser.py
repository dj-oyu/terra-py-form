"""Tests for cold/parser.py"""
import pytest
import yaml

from terra_py_form.cold.parser import (
    Parser,
    ParserError,
    Resource,
    InfraDefinition,
)


class TestParser:
    """Tests for Parser class."""

    def test_parse_empty_file_raises(self, tmp_path):
        """Parsing empty file raises error."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")

        parser = Parser()
        with pytest.raises(ParserError, match="Empty YAML file"):
            parser.parse(empty_file)

    def test_parse_missing_type_raises(self):
        """Resource without type field raises error."""
        yaml_content = """
resources:
  my_resource:
    properties:
      foo: bar
"""
        parser = Parser()
        with pytest.raises(ParserError, match="missing 'type' field"):
            parser.parse_string(yaml_content)

    def test_parse_missing_resources_raises(self):
        """YAML without resources section raises error."""
        yaml_content = """
version: "1.0"
variables:
  region: us-east-1
"""
        parser = Parser()
        with pytest.raises(ParserError, match="No 'resources' section"):
            parser.parse_string(yaml_content)

    def test_parse_basic_resource(self):
        """Parse basic resource correctly."""
        yaml_content = """
version: "1.0"
variables:
  region: us-east-1

resources:
  my_vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16
      tags:
        Name: my-vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.version == "1.0"
        assert result.variables == {"region": "us-east-1"}
        assert len(result.resources) == 1

        res = result.resources[0]
        assert res.name == "my_vpc"
        assert res.type == "aws:ec2:vpc"
        assert res.properties["cidr_block"] == "10.0.0.0/16"
        assert res.properties["tags"]["Name"] == "my-vpc"

    def test_parse_multiple_resources(self):
        """Parse multiple resources."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16

  subnet:
    type: aws:ec2:subnet
    properties:
      vpc_id: "${ref(vpc)}"
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert len(result.resources) == 2
        names = [r.name for r in result.resources]
        assert "vpc" in names
        assert "subnet" in names

    def test_parse_explicit_depends_on(self):
        """Parse explicit depends_on field."""
        yaml_content = """
resources:
  subnet:
    type: aws:ec2:subnet
    depends_on:
      - vpc

  vpc:
    type: aws:ec2:vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        subnet = next(r for r in result.resources if r.name == "subnet")
        assert subnet.depends_on == ["vpc"]

    def test_parse_depends_on_single_string(self):
        """depends_on accepts single string (converted to list)."""
        yaml_content = """
resources:
  subnet:
    type: aws:ec2:subnet
    depends_on: vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        subnet = result.resources[0]
        assert subnet.depends_on == ["vpc"]

    def test_extract_ref_simple(self):
        """Extract simple ${ref(xxx)} reference."""
        yaml_content = """
resources:
  subnet:
    type: aws:ec2:subnet
    properties:
      vpc_id: "${ref(vpc)}"
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        subnet = result.resources[0]
        assert "vpc" in subnet.source_refs

    def test_extract_ref_nested(self):
        """Extract references from nested structures."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    properties:
      subnet:
        id: "${ref(subnet)}"
        zone: "${ref(az)}"
      security_groups:
        - "${ref(sg1)}"
        - "${ref(sg2)}"
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        instance = result.resources[0]
        assert "subnet" in instance.source_refs
        assert "az" in instance.source_refs
        assert "sg1" in instance.source_refs
        assert "sg2" in instance.source_refs

    def test_extract_ref_no_duplicates(self):
        """References are deduplicated."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    properties:
      subnet_id: "${ref(vpc)}"
      vpc_id: "${ref(vpc)}"
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        instance = result.resources[0]
        assert instance.source_refs.count("vpc") == 1

    def test_extract_ref_dotted(self):
        """Extract ref target before dot (vpc.id -> vpc)."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    properties:
      vpc_id: "${ref(vpc.id)}"
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        instance = result.resources[0]
        assert "vpc" in instance.source_refs

    def test_parse_file_not_found(self):
        """Parsing non-existent file raises error."""
        parser = Parser()
        with pytest.raises(ParserError, match="File not found"):
            parser.parse("/nonexistent/path.yaml")

    def test_parse_resource_must_be_dict(self):
        """Resource definition must be a dictionary."""
        yaml_content = """
resources:
  bad_resource: just_a_string
"""
        parser = Parser()
        with pytest.raises(ParserError, match="must be a dictionary"):
            parser.parse_string(yaml_content)

    def test_parse_default_version(self):
        """Default version is 1.0 when not specified."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.version == "1.0"


class TestResource:
    """Tests for Resource dataclass."""

    def test_resource_defaults(self):
        """Resource has sensible defaults."""
        res = Resource(name="test", type="aws:ec2:vpc")

        assert res.properties == {}
        assert res.depends_on == []
        assert res.source_refs == []

    def test_resource_full(self):
        """Resource accepts all fields."""
        res = Resource(
            name="test",
            type="aws:ec2:vpc",
            properties={"foo": "bar"},
            depends_on=["dep1"],
            source_refs=["ref1"],
        )

        assert res.properties == {"foo": "bar"}
        assert res.depends_on == ["dep1"]
        assert res.source_refs == ["ref1"]


class TestInfraDefinition:
    """Tests for InfraDefinition dataclass."""

    def test_infra_definition_defaults(self):
        """InfraDefinition has sensible defaults."""
        infra = InfraDefinition(version="1.0", variables={}, resources=[])

        assert infra.variables == {}

    def test_infra_definition_full(self):
        """InfraDefinition accepts all fields."""
        res = Resource(name="vpc", type="aws:ec2:vpc")
        infra = InfraDefinition(
            version="2.0",
            variables={"region": "us-east-1"},
            resources=[res],
        )

        assert infra.version == "2.0"
        assert infra.variables == {"region": "us-east-1"}
        assert len(infra.resources) == 1
