"""Typed model for the alembic external-adapter protocol.

These dataclasses mirror the JSON shapes the alembic host exchanges with an
adapter. The host serializes the whole request -- including the YAML ``setup:``
block -- as JSON, so this SDK needs no third-party dependencies.

The types fall into two groups:

* parsed from the request (``Object``, ``Op`` and its ``Create``/``Update``/
  ``Delete`` variants, ``Schema``, ``State``): these have ``from_json``.
* produced by the adapter (``ExternalObject``, ``AppliedOp``, ``ApplyReport``,
  ``ProvisionReport``): these have ``to_json`` and skip empty optional fields to
  match the Rust serializer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# protocol version this SDK speaks. bumped in lockstep with the host.
PROTOCOL_VERSION = 1

# a backend identifier is an integer or a string (uuid, slug, ...).
BackendId = int | str

# the canonical representation of a `{string: json}` attrs/key map.
JsonMap = dict


# --------------------------------------------------------------------------- #
# schema                                                                       #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class FieldType:
    """A schema field type.

    ``kind`` is a scalar ("string", "int", "ip_address", "cidr", ...) or one of
    the composite kinds: "enum" (with ``values``), "list" (with ``item``), "map"
    (with ``value``), or "ref"/"list_ref" (with ``target``). The composite
    attributes are ``None`` for scalar kinds.
    """

    kind: str
    values: list[str] | None = None
    item: FieldType | None = None
    value: FieldType | None = None
    target: str | None = None

    @classmethod
    def from_json(cls, data: Any) -> FieldType:
        if isinstance(data, str):
            return cls(kind=data)
        if isinstance(data, dict):
            return _field_type_from_obj(data)
        raise ValueError("field type must be a string or object")


def _field_type_from_obj(data: dict) -> FieldType:
    kind = data.get("type")
    if not isinstance(kind, str):
        raise ValueError("field type requires a string 'type'")
    if kind == "enum":
        return FieldType(kind="enum", values=list(data.get("values", [])))
    if kind == "list":
        return FieldType(kind="list", item=FieldType.from_json(data["item"]))
    if kind == "map":
        return FieldType(kind="map", value=FieldType.from_json(data["value"]))
    if kind in ("ref", "list_ref"):
        return FieldType(kind=kind, target=data.get("target"))
    return FieldType(kind=kind)


@dataclass
class FieldSchema:
    """Metadata for a single field: its type and constraints."""

    type: FieldType
    required: bool = False
    nullable: bool = False
    format: str | None = None
    pattern: str | None = None
    description: str | None = None

    @classmethod
    def from_json(cls, data: dict) -> FieldSchema:
        # composite type info ("item"/"value"/"values"/"target") lives next to
        # "type" in a FieldSchema, mirroring the host's deserializer.
        return cls(
            type=_field_type_from_obj(data),
            required=bool(data.get("required", False)),
            nullable=bool(data.get("nullable", False)),
            format=data.get("format"),
            pattern=data.get("pattern"),
            description=data.get("description"),
        )


@dataclass
class TypeSchema:
    """Key fields and attribute fields for one object type."""

    key: dict[str, FieldSchema] = field(default_factory=dict)
    fields: dict[str, FieldSchema] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> TypeSchema:
        return cls(
            key={k: FieldSchema.from_json(v) for k, v in (data.get("key") or {}).items()},
            fields={k: FieldSchema.from_json(v) for k, v in (data.get("fields") or {}).items()},
        )


@dataclass
class Schema:
    """The schema for the types in play, keyed by type name."""

    types: dict[str, TypeSchema] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> Schema:
        raw = (data or {}).get("types", {})
        return cls(types={name: TypeSchema.from_json(ts) for name, ts in raw.items()})


# --------------------------------------------------------------------------- #
# objects and operations (request side)                                        #
# --------------------------------------------------------------------------- #


@dataclass
class Object:
    """An IR object: a stable uid, a type, a natural key, and attrs."""

    uid: str
    type_name: str
    key: JsonMap = field(default_factory=dict)
    attrs: JsonMap = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict) -> Object:
        type_name = data.get("type", data.get("kind"))
        if type_name is None:
            raise ValueError("object missing 'type'")
        return cls(
            uid=data["uid"],
            type_name=type_name,
            key=dict(data.get("key") or {}),
            attrs=dict(data.get("attrs") or {}),
        )

    def to_json(self) -> dict:
        return {"uid": self.uid, "type": self.type_name, "key": self.key, "attrs": self.attrs}


@dataclass
class FieldChange:
    """A single field-level change on an update op."""

    field: str
    from_value: Any = None
    to_value: Any = None

    @classmethod
    def from_json(cls, data: dict) -> FieldChange:
        return cls(field=data["field"], from_value=data.get("from"), to_value=data.get("to"))


@dataclass
class Op:
    """Base class for a plan operation. See ``Create``/``Update``/``Delete``."""

    uid: str
    type_name: str


@dataclass
class Create(Op):
    """Create a new backend object from ``desired``."""

    desired: Object


@dataclass
class Update(Op):
    """Update an existing backend object identified by ``backend_id``."""

    desired: Object
    changes: list[FieldChange] = field(default_factory=list)
    backend_id: BackendId | None = None


@dataclass
class Delete(Op):
    """Delete the backend object identified by ``backend_id``/``key``."""

    key: JsonMap = field(default_factory=dict)
    backend_id: BackendId | None = None


def op_from_json(data: dict) -> Op:
    """Parse a plan operation from its tagged JSON form."""
    kind = data.get("op")
    uid = data["uid"]
    type_name = data["type_name"]
    if kind == "create":
        return Create(uid=uid, type_name=type_name, desired=Object.from_json(data["desired"]))
    if kind == "update":
        return Update(
            uid=uid,
            type_name=type_name,
            desired=Object.from_json(data["desired"]),
            changes=[FieldChange.from_json(c) for c in data.get("changes") or []],
            backend_id=data.get("backend_id"),
        )
    if kind == "delete":
        return Delete(
            uid=uid,
            type_name=type_name,
            key=dict(data.get("key") or {}),
            backend_id=data.get("backend_id"),
        )
    raise ValueError(f"unknown op kind: {kind!r}")


# --------------------------------------------------------------------------- #
# state (request side)                                                         #
# --------------------------------------------------------------------------- #


@dataclass
class State:
    """The engine's uid -> backend_id mappings, keyed by type name."""

    mappings: dict[str, dict[str, BackendId]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Any) -> State:
        raw = (data or {}).get("mappings") or {}
        return cls(mappings={t: dict(m) for t, m in raw.items()})

    def backend_id(self, type_name: str, uid: str) -> BackendId | None:
        """Look up the backend id mapped to ``uid`` for ``type_name``, if any."""
        return self.mappings.get(type_name, {}).get(uid)


# --------------------------------------------------------------------------- #
# adapter results (response side)                                              #
# --------------------------------------------------------------------------- #


@dataclass
class ExternalObject:
    """An object observed on the backend, returned from ``read``."""

    type_name: str
    key: JsonMap = field(default_factory=dict)
    attrs: JsonMap = field(default_factory=dict)
    backend_id: BackendId | None = None

    def to_json(self) -> dict:
        out: dict = {"type_name": self.type_name, "key": self.key, "attrs": self.attrs}
        if self.backend_id is not None:
            out["backend_id"] = self.backend_id
        return out


@dataclass
class AppliedOp:
    """The result of applying one operation, recorded in an ``ApplyReport``."""

    uid: str
    type_name: str
    backend_id: BackendId | None = None

    def to_json(self) -> dict:
        out: dict = {"uid": self.uid, "type_name": self.type_name}
        if self.backend_id is not None:
            out["backend_id"] = self.backend_id
        return out


@dataclass
class ProvisionReport:
    """Schema elements provisioned by ``ensure_schema``."""

    created_fields: list[str] = field(default_factory=list)
    created_tags: list[str] = field(default_factory=list)
    created_object_types: list[str] = field(default_factory=list)
    created_object_fields: list[str] = field(default_factory=list)
    deprecated_object_types: list[str] = field(default_factory=list)
    deprecated_object_fields: list[str] = field(default_factory=list)
    deleted_object_types: list[str] = field(default_factory=list)
    deleted_object_fields: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        # every field is optional on the host side (serde defaults); emit
        # created_fields/created_tags unconditionally as the common case and
        # omit the rest when empty to keep responses small.
        out: dict = {"created_fields": self.created_fields, "created_tags": self.created_tags}
        for name in (
            "created_object_types",
            "created_object_fields",
            "deprecated_object_types",
            "deprecated_object_fields",
            "deleted_object_types",
            "deleted_object_fields",
        ):
            value = getattr(self, name)
            if value:
                out[name] = value
        return out


@dataclass
class Capabilities:
    """The adapter's role, reported to the host by ``capabilities``.

    ``role`` is one of ``"adapter"`` (read+write, the default), ``"emitter"``
    (write-only), or ``"observer"`` (read-only).
    """

    role: str = "adapter"

    _VALID_ROLES = frozenset({"adapter", "emitter", "observer"})

    def to_json(self) -> dict:
        if self.role not in self._VALID_ROLES:
            raise ValueError(
                f"invalid role {self.role!r}, expected one of {sorted(self._VALID_ROLES)}"
            )
        return {"role": self.role}


@dataclass
class ApplyReport:
    """Aggregated result of a ``write``: the ops applied plus any provisioning."""

    applied: list[AppliedOp] = field(default_factory=list)
    previously_applied_count: int | None = None
    provision: ProvisionReport | None = None

    def to_json(self) -> dict:
        out: dict = {"applied": [op.to_json() for op in self.applied]}
        if self.previously_applied_count is not None:
            out["previously_applied_count"] = self.previously_applied_count
        if self.provision is not None:
            out["provision"] = self.provision.to_json()
        return out
