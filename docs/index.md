# alembic-adapter-sdk

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

the sdk has no runtime dependencies; it speaks json with the stdlib.

## quick example

```python
from alembic_adapter import Adapter, ApplyReport, AppliedOp, Create, run


class MyAdapter(Adapter):
    def setup(self, config):
        # `config` is the parsed `setup:` block from the backend config.
        self.host = (config or {}).get("host", "http://localhost:8080")

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

`run` reads one request from stdin, dispatches it, and writes a
newline-terminated json response to stdout. any exception your adapter raises is
turned into a well-formed `{"ok": false, "error": ...}` response.

## next steps

- [writing an adapter](writing-an-adapter.md) - the `Adapter` class, wiring into
  alembic, and a copyable example.
- [protocol reference](protocol.md) - the methods, the typed model, and the wire
  shapes.
