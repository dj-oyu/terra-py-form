"""Extended tests for cold/parser.py - edge cases."""
import pytest

from terra_py_form.cold.parser import (
    Parser,
    ParserError,
    Resource,
    InfraDefinition,
    REF_PATTERN,
    VAR_PATTERN,
)


class TestParserEdgeCases:
    """Edge case tests for Parser."""

    def test_parse_null_yaml_raises(self):
        """Parsing YAML with only null raises error."""
        parser = Parser()
        with pytest.raises(ParserError, match="Empty"):
            parser.parse_string("")

    def test_parse_only_comments_raises(self):
        """Parsing YAML with only comments raises error."""
        yaml_content = """
# This is a comment
# Another comment
"""
        parser = Parser()
        with pytest.raises(ParserError, match="Empty"):
            parser.parse_string(yaml_content)

    def test_parse_empty_resources_dict(self):
        """Empty resources dict is valid."""
        yaml_content = """
resources: {}
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)
        assert result.resources == []

    def test_parse_resource_without_properties(self):
        """Resource without properties field is valid."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        vpc = result.resources[0]
        assert vpc.properties == {}
        assert vpc.depends_on == []

    def test_parse_empty_depends_on(self):
        """Empty depends_on list is valid."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    depends_on: []
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.resources[0].depends_on == []

    def test_parse_depends_on_multiple_strings(self):
        """depends_on with multiple items."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    depends_on:
      - vpc
      - subnet
      - sg
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.resources[0].depends_on == ["vpc", "subnet", "sg"]

    def test_parse_variables_empty(self):
        """Empty variables is valid."""
        yaml_content = """
variables: {}
resources:
  vpc:
    type: aws:ec2:vpc
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.variables == {}

    def test_parse_complex_yaml_structure(self):
        """Parse complex YAML with all features."""
        yaml_content = """
version: "2.0"
variables:
  region: us-east-1
  env: prod

resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      cidr_block: 10.0.0.0/16
      tags:
        Environment: ${var.env}
        Region: ${var.region}

  subnet_a:
    type: aws:ec2:subnet
    depends_on:
      - vpc
    properties:
      vpc_id: ${ref(vpc.id)}
      availability_zone: ${var.region}a

  subnet_b:
    type: aws:ec2:subnet
    depends_on: vpc
    properties:
      vpc_id: ${ref(vpc.id)}
      availability_zone: ${var.region}b

  sg:
    type: aws:ec2:security_group
    properties:
      vpc_id: ${ref(vpc)}
      name: ${var.env}-sg
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        assert result.version == "2.0"
        assert result.variables["region"] == "us-east-1"
        assert len(result.resources) == 4

    def test_parse_integer_property(self):
        """Parse integer properties."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    properties:
      instance_type: t3.micro
      volume_size: 20
      count: 1
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        props = result.resources[0].properties
        assert props["volume_size"] == 20
        assert props["count"] == 1

    def test_parse_boolean_property(self):
        """Parse boolean properties."""
        yaml_content = """
resources:
  vpc:
    type: aws:ec2:vpc
    properties:
      enable_dns_hostnames: true
      enable_dns_support: false
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        props = result.resources[0].properties
        assert props["enable_dns_hostnames"] is True
        assert props["enable_dns_support"] is False

    def test_parse_list_property(self):
        """Parse list properties."""
        yaml_content = """
resources:
  instance:
    type: aws:ec2:instance
    properties:
      security_groups:
        - sg-1
        - sg-2
      tags:
        - key: Name
          value: my-instance
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        props = result.resources[0].properties
        assert props["security_groups"] == ["sg-1", "sg-2"]

    def test_parse_nested_dict_property(self):
        """Parse nested dictionary properties."""
        yaml_content = """
resources:
  lb:
    type: aws:elb:load_balancer
    properties:
      listener:
        Protocol: HTTP
        Port: 80
      health_check:
        target: HTTP:80/health
        interval: 30
        timeout: 5
"""
        parser = Parser()
        result = parser.parse_string(yaml_content)

        props = result.resources[0].properties
        assert props["listener"]["Protocol"] == "HTTP"
        assert props["health_check"]["interval"] == 30


class TestRefPattern:
    """Tests for REF_PATTERN regex."""

    def test_simple_ref(self):
        """Simple ref pattern matches."""
        assert REF_PATTERN.findall("${ref(vpc)}") == ["vpc"]

    def test_dotted_ref(self):
        """Dotted ref pattern extracts base."""
        assert REF_PATTERN.findall("${ref(vpc.id)}") == ["vpc.id"]

    def test_multiple_refs(self):
        """Multiple refs in string."""
        result = REF_PATTERN.findall("${ref(vpc)} and ${ref(subnet)}")
        assert result == ["vpc", "subnet"]

    def test_no_ref(self):
        """No ref returns empty."""
        assert REF_PATTERN.findall("no ref here") == []

    def test_ref_in_list_value(self):
        """Refs in list values are found."""
        text = 'security_groups: ["${ref(sg1)}", "${ref(sg2)}"]'
        assert REF_PATTERN.findall(text) == ["sg1", "sg2"]


class TestVarPattern:
    """Tests for VAR_PATTERN regex."""

    def test_simple_var(self):
        """Simple var pattern matches."""
        assert VAR_PATTERN.findall("${var.region}") == ["region"]

    def test_no_var(self):
        """No var returns empty."""
        assert VAR_PATTERN.findall("no var here") == []


class TestExtractRefsEdgeCases:
    """Edge case tests for _extract_refs."""

    def test_extract_from_none_value(self):
        """Extract refs from None value."""
        parser = Parser()
        # Should not crash
        refs = parser._extract_refs(None)
        assert refs == []

    def test_extract_from_integer(self):
        """Extract refs from integer."""
        parser = Parser()
        refs = parser._extract_refs(123)
        assert refs == []

    def test_extract_from_boolean(self):
        """Extract refs from boolean."""
        parser = Parser()
        refs = parser._extract_refs(True)
        assert refs == []

    def test_extract_from_list_of_strings(self):
        """Extract refs from list of strings."""
        parser = Parser()
        refs = parser._extract_refs(["${ref(vpc)}", "${ref(subnet)}"])
        assert refs == ["vpc", "subnet"]

    def test_extract_deeply_nested(self):
        """Extract refs from deeply nested structures."""
        parser = Parser()
        nested = {
            "level1": {
                "level2": {
                    "level3": {
                        "vpc_id": "${ref(vpc)}"
                    }
                }
            }
        }
        refs = parser._extract_refs(nested)
        assert "vpc" in refs

    def test_extract_multiple_refs_same_key(self):
        """Multiple refs for same target in different places."""
        parser = Parser()
        props = {
            "subnet_a": "${ref(vpc)}",
            "subnet_b": "${ref(vpc)}",
            "subnet_c": "${ref(vpc)}",
        }
        refs = parser._extract_refs(props)
        # Should be deduplicated
        assert refs.count("vpc") == 1


class TestParserRepr:
    """Tests for Parser repr/str."""

    def test_parser_error_message(self):
        """ParserError has useful message."""
        error = ParserError("Test error")
        assert "Test error" in str(error)
