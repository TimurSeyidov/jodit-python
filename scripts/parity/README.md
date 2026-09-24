# Parity with jodit-nodejs

Three tools check the port against a checkout of [jodit-nodejs](https://github.com/jodit/jodit-nodejs) (copied to `.cache/parity`, never modified):

| Command | What it does |
|---|---|
| `make parity` | Runs the jodit-nodejs Jest suite with its test server replaced by jodit-python connectors (`scripts/parity/test-server.ts` asks `scripts/parity/server.py` for an instance per test) |
| `make parity-compare` | Sends the same edge-case requests to both connectors and diffs the answers |
| `make parity-demo` | Opens the jodit-nodejs demo (Jodit PRO file browser) in headless Chrome against both, lists, opens a folder and uploads a file, and records every request, answer and a screenshot |

`NODEJS=path/to/jodit-nodejs` points to another checkout (default `../jodit-nodejs`); `make parity ARGS=src/v1/files` runs part of the suite. Tests whose configuration holds functions or adapter objects cannot cross the process boundary; they are mirrored in `tests/integration/test_nodejs_parity.py`. Deliberate differences are listed in `scripts/parity/compare.py` (`KNOWN`).
