# terra-py-form

AWS Infrastructure as Code tool with YAML and Python.

## Overview

`terra-py-form` is a lightweight IaC tool that lets you define AWS resources in YAML, visualizes dependencies as a DAG, and shows a dry-run plan before applying.

## Installation

```bash
pip install -e .
```

## Quick Start

```bash
# Show dry-run plan
terra-py-form plan examples/simple.yaml

# Apply resources
terra-py-form apply examples/simple.yaml

# Show current state
terra-py-form state show
```

## YAML Example

```yaml
version: "1.0"

resources:
  vpc:
    type: aws_vpc
    properties:
      cidr_block: "10.0.0.0/16"

  subnet:
    type: aws_subnet
    properties:
      vpc_id: ${vpc.id}
      cidr_block: "10.0.1.0/24"
    depends_on:
      - vpc
```

## Features

- **Dependency Graph**: Automatically resolves `${resource.property}` references
- **Cycle Detection**: Errors on circular dependencies
- **Dry-Run**: Shows create/update/delete plan before applying
- **State Management**: Tracks resources in `state.json`

## License

MIT
