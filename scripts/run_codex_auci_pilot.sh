#!/usr/bin/env bash
set -euo pipefail

pilot_runtime="$(mktemp -d "${TMPDIR:-/tmp}/i-have-adhd-codex-pilot.XXXXXX")"
cleanup() {
  rm -rf -- "$pilot_runtime"
}
trap cleanup EXIT

mkdir -p "$pilot_runtime/work"
source_codex_home="${CODEX_SOURCE_HOME:-${CODEX_HOME:-$HOME/.codex}}"
auth_source="$source_codex_home/auth.json"
if [[ ! -f "$auth_source" ]]; then
  echo "Codex authentication not found at $auth_source" >&2
  exit 2
fi
ln -s "$auth_source" "$pilot_runtime/auth.json"

CODEX_HOME="$pilot_runtime" "${CODEX_BIN:-codex}" exec \
  --ephemeral \
  --ignore-user-config \
  --ignore-rules \
  --disable apps \
  --disable hooks \
  --disable plugins \
  --disable goals \
  --disable memories \
  --disable skill_search \
  --disable skill_mcp_dependency_install \
  --disable workspace_dependencies \
  --disable recommended_plugins \
  --sandbox read-only \
  --skip-git-repo-check \
  --cd "$pilot_runtime/work" \
  --model gpt-5.6-luna \
  --json \
  "$@"
