#!/usr/bin/env bash
set -euo pipefail

PLUGIN_PREFIX="QDB_TEST_REPORT"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PLUGIN_DIR}/.venv"
TEST_REPORT_PY="${PLUGIN_DIR}/lib/test_report_plugin.py"

# Git Bash, the shell of the hooks on the Windows agents.
on_windows() {
  [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || -n "${SYSTEMROOT:-}" ]]
}

# The Python the agent image names for Buildkite plugins, and no other:
# QDB_CICD_AGENT_PLUGIN_PYTHON, one version on every agent. Nothing is
# searched, so every job builds its venv with the same interpreter. The Windows
# image names a Windows path (C:\Python3.13-64\python.exe), which cygpath turns
# into the form Git Bash runs.
plugin_python() {
  local named="${QDB_CICD_AGENT_PLUGIN_PYTHON:-}"
  if [[ -n "${named}" ]] && on_windows; then
    cygpath -u "${named}"
  else
    printf '%s\n' "${named}"
  fi
}

PYTHON3_CMD="$(plugin_python)"

if on_windows; then
  VENV_BIN="${VENV_DIR}/Scripts"
else
  VENV_BIN="${VENV_DIR}/bin"
fi

plugin_read_config() {
  local var="BUILDKITE_PLUGIN_${PLUGIN_PREFIX}_${1}"
  local default="${2:-}"
  echo "${!var:-$default}"
}

plugin_read_list() {
  local prefix="BUILDKITE_PLUGIN_${PLUGIN_PREFIX}_${1}"
  local i=0
  local parameter="${prefix}_${i}"
  if [[ -n "${!parameter:-}" ]]; then
    while [[ -n "${!parameter:-}" ]]; do
      echo "${!parameter}"
      i=$((i+1))
      parameter="${prefix}_${i}"
    done
  elif [[ -n "${!prefix:-}" ]]; then
    echo "${!prefix}"
  fi
}

run_test_report_py() {
  "${VENV_BIN}/python" "${TEST_REPORT_PY}" "$@"
}

plugin_trace_command() {
  local stage="$1"
  shift
  local started=${SECONDS}
  local status=0
  local enabled=false
  case "$(plugin_read_config LOG_LEVEL error)" in
    debug|DEBUG|info|INFO) enabled=true ;;
  esac
  if [[ "$enabled" == true ]]; then
    echo "INFO  trace start stage=${stage}" >&2
  fi
  "$@" || status=$?
  if [[ "$enabled" == true ]]; then
    echo "INFO  trace end stage=${stage} wall_s=$((SECONDS - started)) exit_code=${status}" >&2
  fi
  return "$status"
}
