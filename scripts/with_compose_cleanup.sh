#!/usr/bin/env bash
set -u

docker_bin="${DOCKER_BIN:-docker}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
repo_root="$(cd -- "$script_dir/.." && pwd -P)" || exit 2

derive_build_identity() {
  local build_info="$repo_root/frontend/public/build-info.json"
  local field="$1"
  local value=""
  if [[ -f "$build_info" ]]; then
    value="$(python3 - "$build_info" "$field" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
value = payload.get(sys.argv[2])
if isinstance(value, str):
    print(value)
PY
)" || return 2
  fi
  if [[ ! "$value" =~ ^[0-9a-f]{40}$ ]]; then
    echo "compose-wrapper-error:invalid-build-identity:$field" >&2
    return 2
  fi
  printf '%s' "$value"
}

if [[ -z "${TWIN_RUNTIME_SOURCE_COMMIT_SHA:-}" ]]; then
  TWIN_RUNTIME_SOURCE_COMMIT_SHA="$(derive_build_identity runtime_source_commit_sha)" || exit $?
  export TWIN_RUNTIME_SOURCE_COMMIT_SHA
fi
if [[ -z "${TWIN_RELEASE_COMMIT_SHA:-}" ]]; then
  TWIN_RELEASE_COMMIT_SHA="$(derive_build_identity release_commit_sha)" || exit $?
  export TWIN_RELEASE_COMMIT_SHA
fi

compose_args=()
services=()
while (($#)); do
  case "$1" in
    -f)
      (($# >= 2)) || { echo "compose-wrapper-error:missing-file" >&2; exit 2; }
      compose_args+=("$1" "$2")
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      services+=("$1")
      shift
      ;;
  esac
done
body=("$@")
if ((${#body[@]} == 0)); then
  echo "compose-wrapper-error:missing-body" >&2
  exit 2
fi
body_status=0
cleanup_status=0
cleaned=0

cleanup() {
  if ((cleaned)); then return; fi
  cleaned=1
  "$docker_bin" compose "${compose_args[@]}" down -v --remove-orphans
  cleanup_status=$?
  if ((cleanup_status != 0)); then
    echo "compose-cleanup-failed:status=$cleanup_status" >&2
  fi
}
finish() {
  local signal_status=${1:-0}
  if ((signal_status != 0 && body_status == 0)); then body_status=$signal_status; fi
  cleanup
  echo "compose-wrapper-status:body_status=$body_status cleanup_status=$cleanup_status" >&2
  if ((body_status != 0)); then exit "$body_status"; fi
  exit "$cleanup_status"
}
trap 'finish 130' INT
trap 'finish 143' TERM
trap 'finish 0' EXIT

if ((${#services[@]} > 0)); then
  "$docker_bin" compose "${compose_args[@]}" up -d --build "${services[@]}" || body_status=$?
else
  "$docker_bin" compose "${compose_args[@]}" up -d --build || body_status=$?
fi
if ((body_status == 0)); then
  for service in $("$docker_bin" compose "${compose_args[@]}" ps --services 2>/dev/null); do
    container_id=$("$docker_bin" compose "${compose_args[@]}" ps -q "$service")
    [[ -n "$container_id" ]] || { body_status=1; break; }
    retries="${COMPOSE_HEALTH_RETRIES:-60}"
    for ((attempt=1; attempt<=retries; attempt++)); do
      state=$("$docker_bin" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null) || state="missing"
      [[ "$state" == "healthy" || "$state" == "running" ]] && break
      [[ "$state" == "unhealthy" || "$state" == "exited" || "$state" == "dead" ]] && { body_status=1; break; }
      sleep 1
    done
    [[ "$state" == "healthy" || "$state" == "running" ]] || body_status=1
    ((body_status == 0)) || break
  done
fi
if ((body_status == 0)); then "${body[@]}" || body_status=$?; fi
exit "$body_status"
