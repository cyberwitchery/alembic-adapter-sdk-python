"""Example alembic external adapter, in Python.

Copy this file, rename ``ExampleAdapter``, and implement ``read``/``write`` for
your backend. Run it as a standalone program; the alembic CLI spawns it as a
subprocess and speaks JSON over stdin/stdout.

Wire it in with a backend config like ``examples/backend.yaml``:

    backend: external
    command: python3
    args: ["examples/example_adapter.py"]
    setup:
      host: http://localhost:8080

Then::

    alembic plan  --backend external --backend-config examples/backend.yaml \\
      -f inventory.yaml -o plan.json
    alembic apply --backend external --backend-config examples/backend.yaml \\
      -p plan.json
"""

from __future__ import annotations

from alembic_adapter import (
    Adapter,
    AppliedOp,
    ApplyReport,
    Create,
    Delete,
    ExternalObject,
    Op,
    Schema,
    State,
    Update,
    run,
)


class ExampleAdapter(Adapter):
    """A read+write backend adapter. Replace with your backend client."""

    def __init__(self) -> None:
        self.host = "http://localhost:8080"

    def setup(self, config) -> None:
        # config is the parsed `setup:` block, usually a dict.
        if isinstance(config, dict) and config.get("host"):
            self.host = config["host"]

    def read(self, schema: Schema, types: list[str], state: State) -> list[ExternalObject]:
        # TODO: query self.host and map each backend record into an
        # ExternalObject (its natural key, observed attrs, and backend_id).
        # Emit-only adapters can just return [].
        return []

    def write(self, schema: Schema, ops: list[Op], state: State) -> ApplyReport:
        report = ApplyReport()
        for op in ops:
            if isinstance(op, Create):
                # TODO: create op.desired on the backend, capture its id.
                backend_id = None
            elif isinstance(op, Update):
                # TODO: patch the record op.backend_id with op.changes.
                backend_id = op.backend_id
            elif isinstance(op, Delete):
                # TODO: delete the record op.backend_id.
                backend_id = op.backend_id
            else:  # pragma: no cover -- exhaustive over the op variants.
                raise ValueError(f"unhandled op: {op!r}")
            report.applied.append(
                AppliedOp(uid=op.uid, type_name=op.type_name, backend_id=backend_id)
            )
        return report

    # optional: provision backend schema (custom fields, types, ...) before
    # apply. the base class default returns an empty ProvisionReport; override
    # ensure_schema if your backend needs setting up first.

    # optional: report the adapter's role. the base class default reports the
    # full read+write "adapter" role; an emit-only adapter returns
    # Capabilities(role="emitter") instead.


if __name__ == "__main__":
    run(ExampleAdapter())
