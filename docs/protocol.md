# protocol reference

an external adapter exchanges one json request and one json response over
stdin/stdout. every request carries a `version` (currently `1`) and a `method`.
the sdk parses the payload into typed objects and serializes your results back,
so you rarely touch the raw json.

## methods

| method           | you receive                | you return                  |
| ---------------- | -------------------------- | --------------------------- |
| `read`           | `schema`, `types`, `state` | `list[ExternalObject]`      |
| `write`          | `schema`, `ops`, `state`   | `ApplyReport`               |
| `ensure_schema`  | `schema`                   | `ProvisionReport`           |
| `preview_schema` | `schema`                   | `ProvisionReport` or `None` |

`preview_schema` is called at plan time to show what `ensure_schema` would
provision without writing; return `None` (the default) if your adapter cannot
preview.

`setup` is the `setup:` block from the backend config (parsed json, usually a
dict); `Adapter.setup` is called once before each request, ahead of the method.

a version mismatch, malformed json, or a non-object request is answered with an
`{"ok": false, "error": ...}` response rather than a crash.

## the model

the typed model mirrors alembic's ir:

- **`Op`** is `Create`, `Update`, or `Delete`; dispatch with `isinstance`.
  `Create` and `Update` carry the full desired `Object`. `Update` also carries
  `changes` (a list of `FieldChange`) and `backend_id`. `Delete` carries `key`
  and `backend_id`.
- **`Object`** has `uid`, `type_name`, `key`, and `attrs`.
- **`ExternalObject`** is what `read` returns: `type_name`, `key`, `attrs`, and
  an optional `backend_id`.
- **`AppliedOp`** records one applied operation in an `ApplyReport`: `uid`,
  `type_name`, and an optional `backend_id`.
- **`State`** holds the engine's `uid -> backend_id` mappings.
  `state.backend_id(type_name, uid)` looks up an object's existing backend id,
  so renames stay stable.
- **`Schema`** parses into `TypeSchema` / `FieldSchema` / `FieldType`, so
  schema-driven adapters can, for example, find reference fields via
  `field.type.kind == "ref"` and `field.type.target`.

## wire shapes

the request envelope flattens the method-specific fields next to `version`,
`setup`, and `method`. a `read` request looks like:

```json
{
  "version": 1,
  "setup": { "host": "http://localhost:8080" },
  "method": "read",
  "schema": { "types": {} },
  "types": ["dcim.device"],
  "state": { "mappings": {} }
}
```

a successful response wraps the result:

```json
{ "ok": true, "result": [ /* ExternalObject list, ApplyReport, ... */ ] }
```

and a failure carries a message instead:

```json
{ "ok": false, "error": "explain what went wrong" }
```

for the full request/response shapes of every method, see alembic's
[external adapter documentation](https://github.com/cyberwitchery/alembic/blob/main/docs/external-adapters.md).
