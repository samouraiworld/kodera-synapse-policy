#!/usr/bin/env bash
# Run the policy inside a real, pinned Synapse and drive it as a third-party client would.
# Exit 0 only when every check passes. Needs Docker; removes its container and moves its data
# directory to the trash on exit.
set -euo pipefail

IMAGE="matrixdotorg/synapse:v1.163.0@sha256:e98ab72138d90fa8b8876c6421fe78a9fdb181c0d7cc690ad740e5173e0c65e6"
NAME="kodera-policy-it-$$"
PORT="${PORT:-18448}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
DATA="$(mktemp -d)"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  trash "$DATA" 2>/dev/null || true
}
trap cleanup EXIT

docker run --rm -e SYNAPSE_SERVER_NAME=it.local -e SYNAPSE_REPORT_STATS=no \
  -v "$DATA:/data" "$IMAGE" generate >/dev/null
cat >>"$DATA/homeserver.yaml" <<YAML
federation_domain_whitelist: []
rc_message: {per_second: 100, burst_count: 1000}
rc_login: {address: {per_second: 100, burst_count: 1000}, account: {per_second: 100, burst_count: 1000}}
rc_invites: {per_room: {per_second: 100, burst_count: 1000}, per_user: {per_second: 100, burst_count: 1000}}
YAML
# WITHOUT_MODULE=1 is the negative control: the same scenario must then fail.
if [ "${WITHOUT_MODULE:-0}" != 1 ]; then
  cat >>"$DATA/homeserver.yaml" <<YAML
modules:
  - module: kodera_synapse_policy.KoderaPolicy
    config:
      agent_user_id: "@kodera-agent:it.local"
YAML
fi
SECRET="$(sed -n 's/^registration_shared_secret: *"\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' "$DATA/homeserver.yaml")"
[ -n "$SECRET" ] || { echo "no registration secret in the generated config"; exit 2; }
docker run -d --name "$NAME" -p "127.0.0.1:$PORT:8008" -e PYTHONPATH=/modules \
  -v "$DATA:/data" -v "$HERE/src:/modules:ro" "$IMAGE" >/dev/null
for _ in $(seq 1 90); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || { docker logs "$NAME" | tail -30; exit 2; }

for user in kodera-agent alice bob carol; do
  docker exec "$NAME" register_new_matrix_user -u "$user" -p "pw-$user-123" --no-admin \
    -k "$SECRET" http://localhost:8008 >/dev/null
done

python3 "$HERE/tests/integration/scenario.py" "$PORT"
