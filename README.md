# jodit-python

Python/FastAPI implementation of the
[Jodit](https://xdsoft.net/jodit/) File Browser and Uploader connector,
API-compatible with [jodit-nodejs](https://github.com/jodit/jodit-nodejs).

> Work in progress.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)

## Quick start

```bash
make sync   # install dependencies
make run    # http://localhost:8081/ping
make menu   # interactive list of commands
```

## Development

```bash
make check  # lint + format check + mypy --strict + tests with coverage
```

## License

MIT
