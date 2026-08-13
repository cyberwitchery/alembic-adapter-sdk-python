"""Protocol-level tests for the alembic adapter SDK.

Run with ``python -m unittest`` (no third-party test deps).
"""

from __future__ import annotations

import io
import json
import unittest

from alembic_adapter import (
    PROTOCOL_VERSION,
    Adapter,
    AppliedOp,
    ApplyReport,
    Capabilities,
    Create,
    Delete,
    ExternalObject,
    FieldType,
    Object,
    ProvisionReport,
    Schema,
    State,
    Update,
    op_from_json,
    run,
)

DEVICE = {
    "uid": "7b8f7a92-8fd0-4667-9a4b-9f3b5c9a4aaa",
    "type": "dcim.device",
    "key": {"name": "leaf01"},
    "attrs": {"name": "leaf01", "primary_ip": "198.51.100.1"},
}


def call(adapter: Adapter, request: dict) -> dict:
    """Drive ``adapter`` through one stdio request/response cycle."""
    out = io.StringIO()
    run(adapter, stdin=io.StringIO(json.dumps(request)), stdout=out)
    text = out.getvalue()
    assert text.endswith("\n"), "response must be newline-terminated"
    return json.loads(text)


def envelope(method: str, **fields) -> dict:
    return {"version": PROTOCOL_VERSION, "setup": {}, "method": method, **fields}


class RecordingAdapter(Adapter):
    def __init__(self) -> None:
        self.host = None
        self.seen_types = None
        self.seen_ops = None

    def setup(self, config) -> None:
        self.host = (config or {}).get("host")

    def read(self, schema, types, state):
        self.seen_types = types
        return [
            ExternalObject(
                type_name="dcim.site",
                key={"name": "site-a"},
                attrs={"name": "Site A"},
                backend_id=1,
            )
        ]

    def write(self, schema, ops, state):
        self.seen_ops = ops
        report = ApplyReport()
        for op in ops:
            report.applied.append(
                AppliedOp(
                    uid=op.uid,
                    type_name=op.type_name,
                    backend_id=getattr(op, "backend_id", None) or "new-id",
                )
            )
        return report


class ReadTests(unittest.TestCase):
    def test_read_serializes_observed_objects(self):
        resp = call(RecordingAdapter(), envelope("read", schema={"types": {}}, types=["dcim.site"]))
        self.assertTrue(resp["ok"])
        self.assertEqual(
            resp["result"],
            [
                {
                    "type_name": "dcim.site",
                    "key": {"name": "site-a"},
                    "attrs": {"name": "Site A"},
                    "backend_id": 1,
                }
            ],
        )

    def test_read_default_is_empty(self):
        resp = call(Adapter(), envelope("read", schema={"types": {}}, types=[]))
        self.assertEqual(resp, {"ok": True, "result": []})

    def test_types_are_passed_through(self):
        adapter = RecordingAdapter()
        call(adapter, envelope("read", schema={"types": {}}, types=["dcim.device", "dcim.site"]))
        self.assertEqual(adapter.seen_types, ["dcim.device", "dcim.site"])


class WriteTests(unittest.TestCase):
    def test_create_op_is_reported_applied(self):
        adapter = RecordingAdapter()
        op = {"op": "create", "uid": DEVICE["uid"], "type_name": "dcim.device", "desired": DEVICE}
        resp = call(adapter, envelope("write", schema={"types": {}}, ops=[op]))
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["result"]["applied"][0]["uid"], DEVICE["uid"])
        self.assertEqual(resp["result"]["applied"][0]["backend_id"], "new-id")
        # the parsed op is a Create carrying the full desired object.
        self.assertIsInstance(adapter.seen_ops[0], Create)
        self.assertEqual(adapter.seen_ops[0].desired.attrs["primary_ip"], "198.51.100.1")

    def test_update_op_carries_changes_and_backend_id(self):
        op = {
            "op": "update",
            "uid": DEVICE["uid"],
            "type_name": "dcim.device",
            "desired": DEVICE,
            "changes": [{"field": "primary_ip", "from": "198.51.100.1", "to": "198.51.100.2"}],
            "backend_id": 42,
        }
        parsed = op_from_json(op)
        self.assertIsInstance(parsed, Update)
        self.assertEqual(parsed.backend_id, 42)
        self.assertEqual(parsed.changes[0].field, "primary_ip")
        self.assertEqual(parsed.changes[0].to_value, "198.51.100.2")

    def test_delete_op_carries_key_and_backend_id(self):
        op = {
            "op": "delete",
            "uid": DEVICE["uid"],
            "type_name": "dcim.device",
            "key": {"name": "leaf01"},
            "backend_id": "dev-1",
        }
        parsed = op_from_json(op)
        self.assertIsInstance(parsed, Delete)
        self.assertEqual(parsed.key, {"name": "leaf01"})
        self.assertEqual(parsed.backend_id, "dev-1")

    def test_unknown_op_kind_errors(self):
        with self.assertRaises(ValueError):
            op_from_json({"op": "frobnicate", "uid": "x", "type_name": "t"})


class EnsureSchemaTests(unittest.TestCase):
    def test_default_ensure_schema_is_empty(self):
        resp = call(Adapter(), envelope("ensure_schema", schema={"types": {}}))
        self.assertEqual(resp, {"ok": True, "result": {"created_fields": [], "created_tags": []}})

    def test_provision_report_omits_empty_optional_sections(self):
        report = ProvisionReport(created_fields=["a"], created_object_types=["dcim.site"])
        self.assertEqual(
            report.to_json(),
            {"created_fields": ["a"], "created_tags": [], "created_object_types": ["dcim.site"]},
        )


class PreviewSchemaTests(unittest.TestCase):
    def test_default_preview_schema_is_null(self):
        # the default adapter cannot preview: a null result is the canonical
        # "unavailable" signal the host maps to Ok(None).
        resp = call(Adapter(), envelope("preview_schema", schema={"types": {}}))
        self.assertEqual(resp, {"ok": True, "result": None})

    def test_preview_schema_returns_report_when_implemented(self):
        class Previewing(Adapter):
            def preview_schema(self, schema):
                return ProvisionReport(created_object_types=["dcim.site"])

        resp = call(Previewing(), envelope("preview_schema", schema={"types": {}}))
        self.assertEqual(
            resp,
            {
                "ok": True,
                "result": {
                    "created_fields": [],
                    "created_tags": [],
                    "created_object_types": ["dcim.site"],
                },
            },
        )


class CapabilitiesTests(unittest.TestCase):
    def test_capabilities_defaults_to_adapter_role(self):
        resp = call(Adapter(), envelope("capabilities"))
        self.assertEqual(resp, {"ok": True, "result": {"role": "adapter"}})

    def test_capabilities_emitter_override(self):
        class EmitOnly(Adapter):
            def capabilities(self):
                return Capabilities(role="emitter")

        resp = call(EmitOnly(), envelope("capabilities"))
        self.assertEqual(resp, {"ok": True, "result": {"role": "emitter"}})

    def test_capabilities_invalid_role_is_an_error(self):
        class Broken(Adapter):
            def capabilities(self):
                return Capabilities(role="scribe")

        resp = call(Broken(), envelope("capabilities"))
        self.assertFalse(resp["ok"])
        self.assertIn("invalid role", resp["error"])


class ProtocolGuardTests(unittest.TestCase):
    def test_version_mismatch_is_rejected(self):
        req = {"version": PROTOCOL_VERSION + 1, "method": "read", "schema": {"types": {}}}
        resp = call(Adapter(), req)
        self.assertFalse(resp["ok"])
        self.assertIn("unsupported protocol version", resp["error"])

    def test_unknown_method_errors(self):
        resp = call(Adapter(), envelope("teleport"))
        self.assertFalse(resp["ok"])
        self.assertIn("unknown method", resp["error"])

    def test_invalid_json_errors(self):
        out = io.StringIO()
        run(Adapter(), stdin=io.StringIO("not json {"), stdout=out)
        resp = json.loads(out.getvalue())
        self.assertFalse(resp["ok"])
        self.assertIn("invalid request", resp["error"])

    def test_adapter_exception_becomes_error_response(self):
        class Boom(Adapter):
            def write(self, schema, ops, state):
                raise RuntimeError("backend on fire")

        resp = call(Boom(), envelope("write", schema={"types": {}}, ops=[]))
        self.assertEqual(resp, {"ok": False, "error": "backend on fire"})


class ModelParsingTests(unittest.TestCase):
    def test_setup_receives_config(self):
        adapter = RecordingAdapter()
        req = envelope("read", schema={"types": {}}, types=[])
        req["setup"] = {"host": "https://nb.example.com"}
        call(adapter, req)
        self.assertEqual(adapter.host, "https://nb.example.com")

    def test_state_backend_id_lookup(self):
        state = State.from_json({"mappings": {"dcim.device": {DEVICE["uid"]: 7}}})
        self.assertEqual(state.backend_id("dcim.device", DEVICE["uid"]), 7)
        self.assertIsNone(state.backend_id("dcim.device", "missing"))

    def test_schema_parses_ref_field_target(self):
        schema = Schema.from_json(
            {
                "types": {
                    "dcim.interface": {
                        "key": {"name": {"type": "string"}},
                        "fields": {"device": {"type": "ref", "target": "dcim.device"}},
                    }
                }
            }
        )
        field = schema.types["dcim.interface"].fields["device"]
        self.assertEqual(field.type, FieldType(kind="ref", target="dcim.device"))

    def test_schema_parses_field_type_nested_under_type(self):
        # what a plan/apply request really carries: the host writes an inline
        # composite type back out nested, with its own metadata keys beside it.
        schema = Schema.from_json(
            {
                "types": {
                    "dcim.interface": {
                        "key": {"name": {"type": "slug", "required": False}},
                        "fields": {
                            "device": {
                                "type": {"type": "ref", "target": "dcim.device"},
                                "required": True,
                                "nullable": False,
                            }
                        },
                    }
                }
            }
        )
        field = schema.types["dcim.interface"].fields["device"]
        self.assertEqual(field.type, FieldType(kind="ref", target="dcim.device"))
        self.assertTrue(field.required)
        self.assertEqual(schema.types["dcim.interface"].key["name"].type, FieldType(kind="slug"))

    def test_schema_parses_nested_list_item(self):
        schema = Schema.from_json(
            {
                "types": {
                    "x.y": {
                        "key": {},
                        "fields": {"tags": {"type": "list", "item": "string"}},
                    }
                }
            }
        )
        field = schema.types["x.y"].fields["tags"]
        self.assertEqual(field.type.kind, "list")
        self.assertEqual(field.type.item, FieldType(kind="string"))

    def test_object_accepts_kind_alias(self):
        obj = Object.from_json({"uid": "u1", "kind": "dcim.site", "key": {"slug": "x"}})
        self.assertEqual(obj.type_name, "dcim.site")
        self.assertEqual(obj.attrs, {})

    def test_object_to_json_uses_type_field(self):
        obj = Object(uid="u1", type_name="dcim.site", key={"slug": "x"}, attrs={"name": "X"})
        self.assertEqual(
            obj.to_json(),
            {"uid": "u1", "type": "dcim.site", "key": {"slug": "x"}, "attrs": {"name": "X"}},
        )

    def test_object_from_json_requires_type(self):
        with self.assertRaises(ValueError):
            Object.from_json({"uid": "u1", "key": {"slug": "x"}})

    def test_field_type_from_json_variants(self):
        self.assertEqual(FieldType.from_json("int"), FieldType(kind="int"))
        self.assertEqual(
            FieldType.from_json({"type": "enum", "values": ["a", "b"]}),
            FieldType(kind="enum", values=["a", "b"]),
        )
        self.assertEqual(
            FieldType.from_json({"type": "map", "value": "int"}),
            FieldType(kind="map", value=FieldType(kind="int")),
        )
        self.assertEqual(
            FieldType.from_json({"type": "list_ref", "target": "dcim.device"}),
            FieldType(kind="list_ref", target="dcim.device"),
        )

    def test_field_type_from_json_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            FieldType.from_json(42)
        with self.assertRaises(ValueError):
            FieldType.from_json({"type": 5})


class SerializationTests(unittest.TestCase):
    def test_external_object_omits_backend_id_when_none(self):
        self.assertEqual(
            ExternalObject(type_name="dcim.site").to_json(),
            {"type_name": "dcim.site", "key": {}, "attrs": {}},
        )

    def test_applied_op_omits_backend_id_when_none(self):
        self.assertEqual(
            AppliedOp(uid="u", type_name="dcim.site").to_json(),
            {"uid": "u", "type_name": "dcim.site"},
        )

    def test_apply_report_includes_optional_fields_when_set(self):
        report = ApplyReport(
            applied=[AppliedOp(uid="u", type_name="t")],
            previously_applied_count=3,
            provision=ProvisionReport(created_fields=["f"]),
        )
        out = report.to_json()
        self.assertEqual(out["previously_applied_count"], 3)
        self.assertEqual(out["provision"], {"created_fields": ["f"], "created_tags": []})

    def test_apply_report_omits_optional_fields_when_unset(self):
        self.assertEqual(ApplyReport().to_json(), {"applied": []})


class BaseAdapterTests(unittest.TestCase):
    def test_base_write_is_not_implemented(self):
        resp = call(Adapter(), envelope("write", schema={"types": {}}, ops=[]))
        self.assertFalse(resp["ok"])
        self.assertIn("does not implement write", resp["error"])

    def test_non_object_request_is_rejected(self):
        out = io.StringIO()
        run(Adapter(), stdin=io.StringIO("[1, 2, 3]"), stdout=out)
        resp = json.loads(out.getvalue())
        self.assertFalse(resp["ok"])
        self.assertIn("expected a JSON object", resp["error"])


if __name__ == "__main__":
    unittest.main()
