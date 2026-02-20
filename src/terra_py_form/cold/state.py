"""State management for terraform-like state file."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ResourceState:
    """State of a single resource."""

    resource_type: str
    identifier: dict[str, str] = field(default_factory=dict)  # {arn, id, etc.}
    properties: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceState":
        return cls(**data)


@dataclass
class State:
    """Terraform-like state file."""

    version: str = "1.0"
    resources: dict[str, ResourceState] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def save(self, path: str | Path) -> None:
        """Save state to JSON file."""
        path = Path(path)
        data = {
            "version": self.version,
            "resources": {
                name: res.to_dict() for name, res in self.resources.items()
            },
            "updated_at": self.updated_at,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "State":
        """Load state from JSON file."""
        path = Path(path)
        if not path.exists():
            return cls()

        with open(path) as f:
            data = json.load(f)

        resources = {}
        resources_data = data.get("resources", {})
        if isinstance(resources_data, dict):
            for name, res_data in resources_data.items():
                resources[name] = ResourceState.from_dict(res_data)

        return cls(
            version=data.get("version") or "1.0",
            resources=resources,
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

    def get(self, resource_name: str) -> ResourceState | None:
        """Get resource state by name."""
        return self.resources.get(resource_name)

    def set(self, resource_name: str, resource_state: ResourceState) -> None:
        """Set resource state."""
        self.resources[resource_name] = resource_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def remove(self, resource_name: str) -> bool:
        """Remove resource state. Returns True if existed."""
        if resource_name in self.resources:
            del self.resources[resource_name]
            self.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def clear(self) -> None:
        """Clear all resource states."""
        self.resources.clear()
        self.updated_at = datetime.now(timezone.utc).isoformat()
