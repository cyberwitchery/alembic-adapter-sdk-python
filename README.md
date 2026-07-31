# alembic-adapter-sdk (python)

a small, dependency-free sdk for writing [alembic](https://github.com/cyberwitchery/alembic)
external adapters in python.

network engineering lives in python, so adapters should be writable there too.
alembic delegates backend i/o to *external adapters*: standalone programs the
alembic host spawns as subprocesses, exchanging one json request and one json
response over stdin/stdout. this sdk handles that protocol so you only write the
backend logic.

the import package is `alembic_adapter`. (the pypi distribution is
`alembic-adapter-sdk`; the bare name `alembic` belongs to sqlalchemy's migration
tool and is unrelated.)

## install

```bash
pip install alembic-adapter-sdk
```

or, from a checkout:

```bash
pip install -e .
```

the sdk has no runtime dependencies; it speaks json with the stdlib.

## writing an adapter

subclass `Adapter`, implement the methods your backend needs, and call `run`:

```python
from alembic_adapter import Adapter, ApplyReport, AppliedOp, Create, run

class MyAdapter(Adapter):
    def setup(self, config):
        # `config` is the parsed `setup:` block from the backend config.
        self.host = (config or {}).get("host", "http://localhost:8080")

    def read(self, schema, types, state):
        # observe backend state -> list[ExternalObject]; the engine diffs it
        # against the desired inventory to build a plan. emit-only adapters
        # return [] (the default).
        return []

    def write(self, schema, ops, state):
        # apply create/update/delete ops, then report what was applied.
        report = ApplyReport()
        for op in ops:
            if isinstance(op, Create):
                ...  # create op.desired on the backend
            report.applied.append(AppliedOp(uid=op.uid, type_name=op.type_name))
        return report

if __name__ == "__main__":
    run(MyAdapter())
```

`run` reads one request from stdin, dispatches it, and writes a
newline-terminated json response to stdout. any exception your adapter raises is
turned into a well-formed `{"ok": false, "error": ...}` response.

see [`examples/example_adapter.py`](examples/example_adapter.py) for a complete,
copyable starting point.

## the protocol

every request carries `version` (currently `1`) and a `method`. the sdk parses
the payload into typed objects and serializes your results back:

| method           | you receive                       | you return                    |
| ---------------- | --------------------------------- | ----------------------------- |
| `read`           | `schema`, `types`, `state`        | `list[ExternalObject]`        |
| `write`          | `schema`, `ops`, `state`          | `ApplyReport`                 |
| `ensure_schema`  | `schema`                          | `ProvisionReport`             |
| `preview_schema` | `schema`                          | `ProvisionReport` or `None`   |
| `capabilities`   | nothing                           | `Capabilities`                |

`preview_schema` is called at plan time to show what `ensure_schema` would
provision without writing; return `None` (the default) if your adapter cannot
preview.

`capabilities` reports the adapter's role: `adapter` (read+write, the default),
`emitter` (write-only), or `observer` (read-only), so the host can reject
`import`/`apply` up front instead of calling into a side that does nothing.

`setup` is the `setup:` block from the backend config (parsed json, usually a
dict); `Adapter.setup` is called once before each request.

the model mirrors alembic's ir:

- `Op` is `Create`, `Update`, or `Delete` (dispatch with `isinstance`). `Create`
  and `Update` carry the full desired `Object`; `Update` also carries `changes`
  and `backend_id`; `Delete` carries `key` and `backend_id`.
- `Object` has `uid`, `type_name`, `key`, and `attrs`.
- `State.backend_id(type_name, uid)` looks up the engine's existing backend id
  for an object, so renames stay stable.
- `Schema` parses into `TypeSchema` / `FieldSchema` / `FieldType`, so
  schema-driven adapters can, for example, find reference fields via
  `field.type.kind == "ref"` and `field.type.target`.

for the full request/response shapes, see alembic's
[`docs/external-adapters.md`](https://github.com/cyberwitchery/alembic/blob/main/docs/external-adapters.md).

## wiring into alembic

point a backend config at your program (see [`examples/backend.yaml`](examples/backend.yaml)):

```yaml
backend: external
command: python3
args: ["examples/example_adapter.py"]
setup:
  host: http://localhost:8080
```

```bash
alembic plan  --backend external --backend-config examples/backend.yaml \
  -f inventory.yaml -o plan.json
alembic apply --backend external --backend-config examples/backend.yaml \
  -p plan.json
```

you can also debug the protocol by hand by piping a request into your adapter:

```bash
echo '{"version":1,"setup":{},"method":"read","schema":{"types":{}},"types":[],"state":{"mappings":{}}}' \
  | python3 examples/example_adapter.py
```

## develop

```bash
pip install -e ".[dev]"

# tests
PYTHONPATH=src python -m unittest discover -s tests

# tests with the coverage gate (fails under 100%, matching ci)
coverage run -m unittest discover -s tests
coverage report

ruff check
ruff format --check
```

## license

Apache-2.0
