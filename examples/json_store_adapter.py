"""A complete alembic external adapter backed by a json file.

Where ``example_adapter.py`` is a skeleton with the backend calls left as TODOs,
this one is a working adapter: it keeps objects in a json file and implements
every method of the contract, so it converges under ``alembic plan``/``apply``
like a real backend does. Read it as a reference for what a finished adapter
looks like; the ci e2e job drives this file with the real alembic cli.

The "backend" is a single json document::

    {
      "next_id": 3,
      "types": ["dcim.site"],
      "objects": {"1": {"type": "dcim.site", "key": {...}, "attrs": {...}}}
    }

Backend ids are the integer keys of ``objects``, which is what a real backend
would assign on create and what the engine stores in its state.

Wire it in with a backend config like::

    backend: external
    command: python3
    args: ["examples/json_store_adapter.py"]
    setup:
      path: store.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alembic_adapter import (
    Adapter,
    AppliedOp,
    ApplyReport,
    Create,
    Delete,
    ExternalObject,
    Op,
    ProvisionReport,
    Schema,
    State,
    Update,
    run,
)


class JsonStoreAdapter(Adapter):
    """A read+write adapter over a json file."""

    def __init__(self) -> None:
        self.path = Path("store.json")

    def setup(self, config: Any) -> None:
        if isinstance(config, dict) and config.get("path"):
            self.path = Path(config["path"])

    # ----------------------------------------------------------------- store #

    def _load(self) -> dict:
        if not self.path.exists():
            return {"next_id": 1, "types": [], "objects": {}}
        return json.loads(self.path.read_text())

    def _save(self, store: dict) -> None:
        self.path.write_text(json.dumps(store, indent=2, sort_keys=True))

    # -------------------------------------------------------------- contract #

    def read(self, schema: Schema, types: list[str], state: State) -> list[ExternalObject]:
        """Return every stored object of a requested type.

        The engine diffs these against the desired inventory, so a converged
        store plans no operations at all.
        """
        store = self._load()
        wanted = set(types)
        return [
            ExternalObject(
                type_name=record["type"],
                key=record["key"],
                attrs=record["attrs"],
                # ids are strings as json object keys; the backend's own type is
                # an int, and the engine keeps whichever we report.
                backend_id=int(backend_id),
            )
            for backend_id, record in sorted(store["objects"].items(), key=lambda kv: int(kv[0]))
            if not wanted or record["type"] in wanted
        ]

    def write(self, schema: Schema, ops: list[Op], state: State) -> ApplyReport:
        """Apply the plan's operations to the store, in the order given."""
        store = self._load()
        report = ApplyReport()
        for op in ops:
            if isinstance(op, Create):
                backend_id = store["next_id"]
                store["next_id"] += 1
                store["objects"][str(backend_id)] = {
                    "type": op.type_name,
                    "key": op.desired.key,
                    "attrs": op.desired.attrs,
                }
            elif isinstance(op, Update):
                # the engine hands us both the full desired object and the
                # field-level `changes`; a json store can just take `desired`,
                # a rest backend would patch only the changed fields.
                backend_id = op.backend_id
                record = store["objects"].get(str(backend_id))
                if record is None:
                    raise ValueError(f"update for unknown backend id {backend_id!r}")
                record["attrs"].update(op.desired.attrs)
                record["key"] = op.desired.key
            elif isinstance(op, Delete):
                backend_id = op.backend_id
                if store["objects"].pop(str(backend_id), None) is None:
                    raise ValueError(f"delete for unknown backend id {backend_id!r}")
            else:  # pragma: no cover -- exhaustive over the op variants.
                raise ValueError(f"unhandled op: {op!r}")
            report.applied.append(
                AppliedOp(uid=op.uid, type_name=op.type_name, backend_id=backend_id)
            )
        self._save(store)
        return report

    def ensure_schema(self, schema: Schema) -> ProvisionReport:
        """Record the types this store now holds, and report what was new."""
        store = self._load()
        created = self._missing_types(store, schema)
        if created:
            store["types"] = sorted(set(store["types"]) | set(created))
            self._save(store)
        return ProvisionReport(created_object_types=created)

    def preview_schema(self, schema: Schema) -> ProvisionReport:
        """Report what ``ensure_schema`` would provision, writing nothing.

        The host calls this at plan time, so the plan can show pending schema
        work before anyone applies it.
        """
        return ProvisionReport(created_object_types=self._missing_types(self._load(), schema))

    @staticmethod
    def _missing_types(store: dict, schema: Schema) -> list[str]:
        known = set(store["types"])
        return sorted(name for name in schema.types if name not in known)


if __name__ == "__main__":
    run(JsonStoreAdapter())
