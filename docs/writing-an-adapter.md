# writing an adapter

subclass `Adapter`, implement the methods your backend needs, and call `run`
from your `__main__`.

```python
from alembic_adapter import Adapter, ApplyReport, AppliedOp, Create, run

class MyAdapter(Adapter):
    def setup(self, config):
        self.host = (config or {}).get("host", "http://localhost:8080")

    def read(self, schema, types, state):
        return []

    def write(self, schema, ops, state):
        report = ApplyReport()
        for op in ops:
            if isinstance(op, Create):
                ...  # create op.desired on the backend
            report.applied.append(AppliedOp(uid=op.uid, type_name=op.type_name))
        return report

if __name__ == "__main__":
    run(MyAdapter())
```

## the methods

`setup` is called once before each request with the parsed `setup:` block from
the backend config (usually a dict, or `None` when none was provided). use it to
read connection details and options.

`read` observes backend state for the requested types and returns a list of
`ExternalObject`. the engine diffs these against the desired inventory to build a
plan. it defaults to returning nothing, which is the right behaviour for
**emit-only** adapters (ones that just render an artifact) - every desired
object then becomes a create.

`write` applies plan operations and returns an `ApplyReport`. dispatch on the op
type with `isinstance`:

```python
from alembic_adapter import Create, Update, Delete

def write(self, schema, ops, state):
    report = ApplyReport()
    for op in ops:
        if isinstance(op, Create):
            backend_id = self.create(op.desired)
        elif isinstance(op, Update):
            self.patch(op.backend_id, op.changes)
            backend_id = op.backend_id
        elif isinstance(op, Delete):
            self.delete(op.backend_id)
            backend_id = op.backend_id
        report.applied.append(
            AppliedOp(uid=op.uid, type_name=op.type_name, backend_id=backend_id)
        )
    return report
```

record a `backend_id` on each `AppliedOp` so the engine can persist the
`uid -> backend_id` mapping in its state store; that keeps identities stable
across renames.

`ensure_schema` provisions backend schema (custom fields, types) before apply.
it defaults to a no-op; override it and return a `ProvisionReport` if your
backend needs setting up first.

`preview_schema` is called at plan time to show what `ensure_schema` would
provision, writing nothing. it defaults to `None` ("cannot preview"); if you
implement `ensure_schema`, implement this too and return the report it would
produce. the report's `deleted_object_types`/`deleted_object_fields` feed the
host's destructive-provisioning gate, so list any schema you would drop.

`capabilities` reports which side of the contract the adapter implements. the
default is the full read+write `adapter` role; an emit-only adapter overrides it
so the host plans every object as a create and rejects `import` up front:

```python
from alembic_adapter import Capabilities

def capabilities(self):
    return Capabilities(role="emitter")
```

## errors

you do not need to catch your own errors. any exception raised in `setup` or a
method implementation is turned into a well-formed
`{"ok": false, "error": "<message>"}` response, and the alembic host surfaces it.

## wiring into alembic

point a backend config at your program:

```yaml
backend: external
command: python3
args: ["examples/example_adapter.py"]
setup:
  host: http://localhost:8080
```

```bash
alembic plan  --backend external --backend-config backend.yaml \
  -f inventory.yaml -o plan.json
alembic apply --backend external --backend-config backend.yaml \
  -p plan.json
```

once the package is installed you can also expose a console script and point
`command` at that instead of `python3 <file>`.

## debugging by hand

an adapter is just a program that reads one json request and writes one json
response, so you can drive it straight from a shell:

```bash
echo '{"version":1,"setup":{},"method":"read","schema":{"types":{}},"types":[],"state":{"mappings":{}}}' \
  | python3 examples/example_adapter.py
```

see [`examples/example_adapter.py`](https://github.com/cyberwitchery/alembic-adapter-sdk-python/blob/main/examples/example_adapter.py)
for a complete, copyable starting point.
