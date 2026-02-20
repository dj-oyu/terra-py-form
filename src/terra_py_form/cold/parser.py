"""YAML parser for infrastructure definitions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Resource:
    """Infrastructure resource representation."""

    name: str  # YAML key: "my_vpc"
    type: str  # "aws:ec2:vpc"
    properties: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)  # ${ref(xxx)}


@dataclass
class InfraDefinition:
    """Complete parsed YAML structure."""

    version: str
    variables: dict
    resources: list[Resource]


# Pattern to match ${ref(xxx)} or ${ref(xxx.yyy)}
REF_PATTERN = re.compile(r"\$\{ref\(([^)]+)\)\}")
# Pattern to match ${var.xxx}
VAR_PATTERN = re.compile(r"\$\{var\.(\w+)\}")


class ParserError(Exception):
    """Parser error."""

    pass


class Parser:
    """Parse YAML infrastructure definition."""

    def parse(self, yaml_path: str | Path) -> InfraDefinition:
        """Parse YAML file into InfraDefinition."""
        path = Path(yaml_path)
        if not path.exists():
            raise ParserError(f"File not found: {yaml_path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        if data is None:
            raise ParserError(f"Empty YAML file: {yaml_path}")

        return self._parse_data(data)

    def parse_string(self, yaml_content: str) -> InfraDefinition:
        """Parse YAML string into InfraDefinition."""
        data = yaml.safe_load(yaml_content)
        if data is None:
            raise ParserError("Empty YAML content")
        return self._parse_data(data)

    def _parse_data(self, data: dict) -> InfraDefinition:
        """Internal: parse dict into InfraDefinition."""
        version = data.get("version", "1.0")
        variables = data.get("variables", {})

        if "resources" not in data:
            raise ParserError("No 'resources' section")
        resources_raw = data.get("resources", {})
        if resources_raw is None:
            resources_raw = {}
        # Empty resources dict {} is valid - means no resources

        resources = []
        for name, resource_def in resources_raw.items():
            if not isinstance(resource_def, dict):
                raise ParserError(
                    f"Resource '{name}' must be a dictionary, got {type(resource_def)}"
                )

            res_type = resource_def.get("type")
            if not res_type:
                raise ParserError(f"Resource '{name}' missing 'type' field")

            properties = resource_def.get("properties", {})
            depends_on = resource_def.get("depends_on", [])
            if isinstance(depends_on, str):
                depends_on = [depends_on]

            # Extract all ${ref(...)} references from properties
            source_refs = self._extract_refs(properties)

            resources.append(
                Resource(
                    name=name,
                    type=res_type,
                    properties=properties,
                    depends_on=depends_on,
                    source_refs=source_refs,
                )
            )

        return InfraDefinition(version=version, variables=variables, resources=resources)

    def _extract_refs(self, value: Any, found: list[str] | None = None) -> list[str]:
        """Recursively extract ${ref(xxx)} references from nested structures."""
        if found is None:
            found = []

        if isinstance(value, str):
            # Check for ${ref(...)} pattern
            for match in REF_PATTERN.finditer(value):
                ref_target = match.group(1).split(".")[0]  # ${ref(vpc.id)} -> "vpc"
                if ref_target not in found:
                    found.append(ref_target)
        elif isinstance(value, dict):
            for v in value.values():
                self._extract_refs(v, found)
        elif isinstance(value, list):
            for item in value:
                self._extract_refs(item, found)

        return found
