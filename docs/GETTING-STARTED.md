# Getting Started

Harborly is a Python SDK and CLI for port identity resolution, spatial search,
and approximate sea-route distances.

> [!IMPORTANT]
> Route results are analytical approximations. Do not use them for navigation,
> voyage planning, or other safety-critical decisions.

## Prerequisites

- Python `>=3.11`
- [uv](https://docs.astral.sh/uv/)
- Git

No environment variables or external services are required for the bundled
registry. The commands below install every optional capability, including
routing, maps, the terminal UI, and the local API service.

## Installation

1. Clone the repository.

   ```bash
   git clone https://github.com/frogiraffe/harborly.git
   ```

2. Enter the checkout.

   ```bash
   cd harborly
   ```

3. Create the project environment and install dependencies.

   ```bash
   uv sync --all-extras
   ```

## First run

Inspect the bundled port registry:

```bash
uv run harborly info
```

The command prints the number of registry records, records per provider, and
the active data directory. Then search for a port and calculate a route:

```bash
uv run harborly search Mersin --country TR
uv run harborly route TRMER GRPIR
```

## Common setup issues

### `uv: command not found`

Install `uv`, then repeat the installation steps. Harborly's lockfile and
documented source-checkout commands use `uv`.

### A route command reports that `searoute` is missing

Routing is an optional capability. Install the routing extra, then retry:

```bash
uv sync --extra routing
uv run harborly route TRMER GRPIR
```

If you installed Harborly as an isolated CLI tool, reinstall it with the same
extra:

```bash
uv tool install --force 'harborly[routing]'
```

## Next steps

- See the [Reference](REFERENCE.md) for library, CLI, HTTP, routing, export,
  data, and TUI details.
- Configure an alternate port registry with [Configuration](CONFIGURATION.md).
- Review [Architecture](ARCHITECTURE.md) before changing implementation code,
  and [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution checks.
