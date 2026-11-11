# migration-runner

[![PyPI version](https://img.shields.io/pypi/v/trysac-migration-runner)](https://pypi.org/project/trysac-migration-runner/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-migration-runner)](LICENSE)
[![CI](https://github.com/Trysac/u285-migration-runner/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u285-migration-runner/actions/workflows/ci.yml)

Run versioned SQL migrations against SQLite with a cross-process lock table, checksums of applied files, transactional apply and rollback, and a dry-run plan

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-migration-runner
# or
uv add trysac-migration-runner
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import migration_runner

# normalize() trims surrounding whitespace and lower-cases the text.
print(migration_runner.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    migration_runner.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
