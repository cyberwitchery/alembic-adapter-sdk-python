"""Python SDK for writing `alembic <https://github.com/cyberwitchery/alembic>`_
external adapters.

An external adapter is a standalone program the alembic host spawns as a
subprocess, speaking one JSON request/response over stdin/stdout. Implement
:class:`Adapter` and call :func:`run`::

    from alembic_adapter import Adapter, ApplyReport, AppliedOp, run

    class MyAdapter(Adapter):
        def setup(self, config):
            self.host = (config or {}).get("host", "http://localhost:8080")

        def write(self, schema, ops, state):
            report = ApplyReport()
            for op in ops:
                report.applied.append(AppliedOp(uid=op.uid, type_name=op.type_name))
            return report

    if __name__ == "__main__":
        run(MyAdapter())
"""

from .model import (
    PROTOCOL_VERSION,
    AppliedOp,
    ApplyReport,
    BackendId,
    Create,
    Delete,
    ExternalObject,
    FieldChange,
    FieldSchema,
    FieldType,
    JsonMap,
    Object,
    Op,
    ProvisionReport,
    Schema,
    State,
    TypeSchema,
    Update,
    op_from_json,
)
from .runtime import Adapter, run

__version__ = "0.1.0"

__all__ = [
    "PROTOCOL_VERSION",
    "Adapter",
    "AppliedOp",
    "ApplyReport",
    "BackendId",
    "Create",
    "Delete",
    "ExternalObject",
    "FieldChange",
    "FieldSchema",
    "FieldType",
    "JsonMap",
    "Object",
    "Op",
    "ProvisionReport",
    "Schema",
    "State",
    "TypeSchema",
    "Update",
    "op_from_json",
    "run",
]
