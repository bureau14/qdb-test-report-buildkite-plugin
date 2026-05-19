#!/usr/bin/env bash
set -euo pipefail

PLUGIN_PREFIX="QDB_TEST_REPORT"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${PLUGIN_DIR}/.venv"
TEST_REPORT_PY="${PLUGIN_DIR}/lib/test_report_plugin.py"

_find_python3() {
  if [[ -n "${QDB_CICD_AGENT_PYTHON3:-}" ]] && [[ -x "${QDB_CICD_AGENT_PYTHON3}" ]]; then
    echo "${QDB_CICD_AGENT_PYTHON3}"
    return
  fi

  for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null \
       && "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3,) else 1)" 2>/dev/null; then
      echo "$cmd"
      return
    fi
  done

  if [[ -n "${SYSTEMROOT:-}" ]]; then
    for dir in /c/Python3.*-64 /c/Python3.*-32 /c/Python3*; do
      if [[ -x "${dir}/python.exe" ]] \
         && "${dir}/python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,) else 1)" 2>/dev/null; then
        echo "${dir}/python.exe"
        return
      fi
    done
  fi
}

PYTHON3_CMD="$(_find_python3 || true)"

if [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || -n "${SYSTEMROOT:-}" ]]; then
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
