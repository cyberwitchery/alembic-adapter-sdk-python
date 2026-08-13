#!/usr/bin/env bash
# real alembic-driven end-to-end test: has the actual alembic cli spawn an
# adapter written with this sdk and converge an inventory through plan/apply,
# then checks that the second plan is empty (idempotent) and that update and
# delete flow through to the store.
#
# this is the cross-language check the unit tests cannot do: every request the
# sdk parses here is one the host really produced, and every response it writes
# is one the host really deserializes. a host-side shape change shows up as a
# failure instead of waiting for a user to hit it.
#
# needs the alembic cli. point $ALEMBIC at it, or have `alembic` on PATH. set
# $PYTHON to pick an interpreter (defaults to python3); it must have this sdk
# installed (`pip install -e .`).
set -uo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

ALEMBIC="${ALEMBIC:-alembic}"
if [ ! -x "$ALEMBIC" ]; then
  resolved="$(command -v "$ALEMBIC" 2>/dev/null || true)"
  [ -n "$resolved" ] && ALEMBIC="$resolved"
fi
if [ ! -x "$ALEMBIC" ]; then
  echo "SKIP: alembic cli not found. set \$ALEMBIC to the alembic binary."
  exit 0
fi

PYTHON="${PYTHON:-python3}"
PYTHON="$(command -v "$PYTHON")" || { echo "need python3"; exit 1; }
"$PYTHON" -c "import alembic_adapter" 2>/dev/null || {
  echo "FAIL - $PYTHON cannot import alembic_adapter (pip install -e .)"
  exit 1
}

ADAPTER="$ROOT/examples/json_store_adapter.py"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cat > "$WORK/backend.yaml" <<EOF
backend: external
command: $PYTHON
args: ["$ADAPTER"]
setup:
  path: $WORK/store.json
EOF

cat > "$WORK/inv.yaml" <<'EOF'
schema:
  types:
    dcim.site:
      key: { slug: { type: slug } }
      fields:
        name:   { type: string }
        slug:   { type: slug }
        status: { type: string }
    dcim.device:
      key: { name: { type: slug } }
      fields:
        name:   { type: string }
        site:   { type: ref, target: dcim.site }
        status: { type: string }
objects:
  - uid: "a4d6a0c3-4e73-4a76-b216-4d38f8c55f3d"
    type: dcim.site
    key:   { slug: "fra1" }
    attrs: { name: "FRA1", slug: "fra1", status: "active" }
  - uid: "7b8f7a92-8fd0-4667-9a4b-9f3b5c9a4b1a"
    type: dcim.device
    key:   { name: "leaf01" }
    attrs: { name: "leaf01", site: "a4d6a0c3-4e73-4a76-b216-4d38f8c55f3d", status: "active" }
EOF

cd "$WORK"
fail=0
B=(--backend external --backend-config backend.yaml)

ops_count() { "$PYTHON" -c "import json,sys; print(len(json.load(open(sys.argv[1])).get('ops',[])))" "$1"; }
# query the adapter's json store: `store '<python expression over s>'`
store() { "$PYTHON" -c "import json; s = json.load(open('store.json')); print($1)"; }
expect() { # <desc> <actual> <wanted>
  if [ "$2" = "$3" ]; then echo "ok   - $1"; else echo "FAIL - $1 (got $2, wanted $3)"; fail=1; fi
}

"$ALEMBIC" validate -f inv.yaml >/dev/null || { echo "FAIL - validate"; fail=1; }

# plan reports the adapter's preview_schema, so both types show up as pending.
"$ALEMBIC" plan -f inv.yaml -o p1.json "${B[@]}" > p1.txt 2>&1
expect "initial plan has 2 creates" "$(ops_count p1.json)" "2"
expect "plan reports the previewed schema" \
  "$(grep -c '^schema preview: 2 object types created$' p1.txt)" "1"

"$ALEMBIC" apply -p p1.json "${B[@]}" >/dev/null
expect "apply wrote both objects to the store" "$(store 'len(s["objects"])')" "2"
expect "apply provisioned both types" "$(store 'len(s["types"])')" "2"

"$ALEMBIC" plan -f inv.yaml -o p2.json "${B[@]}" >/dev/null
expect "re-plan is empty (converged)" "$(ops_count p2.json)" "0"

# update: flip status. the ops carry backend ids from the engine's state, which
# the adapter reported on create.
sed 's/status: "active"/status: "planned"/g' inv.yaml > inv2.yaml
"$ALEMBIC" plan -f inv2.yaml -o p3.json "${B[@]}" >/dev/null
expect "edited inventory plans updates" "$(ops_count p3.json)" "2"
"$ALEMBIC" apply -p p3.json "${B[@]}" >/dev/null
expect "update persisted to the store" \
  "$(store 'sorted(o["attrs"]["status"] for o in s["objects"].values())')" \
  "['planned', 'planned']"

# delete: same intent minus the device (written out, so we need no yaml lib)
cat > inv3.yaml <<'EOF'
schema:
  types:
    dcim.site:
      key: { slug: { type: slug } }
      fields:
        name:   { type: string }
        slug:   { type: slug }
        status: { type: string }
    dcim.device:
      key: { name: { type: slug } }
      fields:
        name:   { type: string }
        site:   { type: ref, target: dcim.site }
        status: { type: string }
objects:
  - uid: "a4d6a0c3-4e73-4a76-b216-4d38f8c55f3d"
    type: dcim.site
    key:   { slug: "fra1" }
    attrs: { name: "FRA1", slug: "fra1", status: "planned" }
EOF
"$ALEMBIC" plan -f inv3.yaml -o p4.json "${B[@]}" --allow-delete >/dev/null
expect "removing an object plans a delete" "$(ops_count p4.json)" "1"
"$ALEMBIC" apply -p p4.json "${B[@]}" --allow-delete >/dev/null
expect "delete persisted (only the site remains)" \
  "$(store '[o["type"] for o in s["objects"].values()]')" \
  "['dcim.site']"

echo
if [ "$fail" -eq 0 ]; then echo "e2e-alembic: all checks passed"; else echo "e2e-alembic: failures above"; fi
exit "$fail"
