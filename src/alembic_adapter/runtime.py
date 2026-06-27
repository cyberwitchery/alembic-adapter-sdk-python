"""stdin/stdout protocol runner for alembic external adapters.

An external adapter is a standalone program. The alembic host spawns it, writes
one JSON request to its stdin, and reads one JSON response from its stdout.
Subclass :class:`Adapter`, implement the methods you need, and call :func:`run`
from your ``__main__``.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from .model import (
    PROTOCOL_VERSION,
    ApplyReport,
    ExternalObject,
    Op,
    ProvisionReport,
    Schema,
    State,
    op_from_json,
)


class Adapter:
    """Base class for an alembic external adapter.

    Override the methods your backend supports. ``read`` defaults to returning
    nothing (the right behaviour for emit-only adapters) and ``ensure_schema``
    defaults to a no-op; ``write`` raises until you implement it.
    """

    def setup(self, config: Any) -> None:
        """Configure the adapter from the ``setup:`` block.

        ``config`` is the parsed ``setup:`` value from the backend config,
        usually a ``dict`` (it may be ``None`` when no setup was provided).
        Called once before each request.
        """

    def read(self, schema: Schema, types: list[str], state: State) -> list[ExternalObject]:
        """Observe backend state for ``types``.

        Return one :class:`ExternalObject` per backend record. The engine diffs
        these against the desired inventory to build a plan. Emit-only adapters
        can leave this as the default empty result.
        """
        return []

    def write(self, schema: Schema, ops: list[Op], state: State) -> ApplyReport:
        """Apply plan operations to the backend.

        Handle each :class:`~alembic_adapter.Create`/``Update``/``Delete`` op,
        then return an :class:`ApplyReport` recording what was applied.
        """
        raise NotImplementedError("adapter does not implement write")

    def ensure_schema(self, schema: Schema) -> ProvisionReport:
        """Provision backend schema before apply. Defaults to a no-op."""
        return ProvisionReport()


def run(adapter: Adapter, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    """Run a single request/response cycle for ``adapter`` over stdio.

    Reads the entire request from ``stdin`` (default :data:`sys.stdin`), handles
    it, and writes a newline-terminated JSON response to ``stdout`` (default
    :data:`sys.stdout`). Any error is reported as a well-formed ``ok: false``
    response rather than a crash, matching the protocol.
    """
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    response = _handle(adapter, source.read())
    sink.write(json.dumps(response))
    sink.write("\n")
    sink.flush()


def _handle(adapter: Adapter, raw: str) -> dict:
    try:
        envelope = json.loads(raw)
    except (ValueError, TypeError) as err:
        return _error(f"invalid request: {err}")

    if not isinstance(envelope, dict):
        return _error("invalid request: expected a JSON object")

    version = envelope.get("version")
    if version != PROTOCOL_VERSION:
        return _error(f"unsupported protocol version {version} (expected {PROTOCOL_VERSION})")

    try:
        adapter.setup(envelope.get("setup"))
        return _dispatch(adapter, envelope)
    except Exception as err:  # noqa: BLE001 -- any adapter error becomes a protocol error.
        return _error(str(err))


def _dispatch(adapter: Adapter, envelope: dict) -> dict:
    method = envelope.get("method")
    if method == "read":
        schema = Schema.from_json(envelope.get("schema"))
        types = list(envelope.get("types") or [])
        state = State.from_json(envelope.get("state"))
        observed = adapter.read(schema, types, state)
        return _ok([obj.to_json() for obj in observed])
    if method == "write":
        schema = Schema.from_json(envelope.get("schema"))
        ops = [op_from_json(op) for op in envelope.get("ops") or []]
        state = State.from_json(envelope.get("state"))
        report = adapter.write(schema, ops, state)
        return _ok(report.to_json())
    if method == "ensure_schema":
        schema = Schema.from_json(envelope.get("schema"))
        report = adapter.ensure_schema(schema)
        return _ok(report.to_json())
    return _error(f"unknown method: {method!r}")


def _ok(result: Any) -> dict:
    return {"ok": True, "result": result}


def _error(message: str) -> dict:
    return {"ok": False, "error": message}
