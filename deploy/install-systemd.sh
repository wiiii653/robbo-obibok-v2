#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="robbo-obibok"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_APP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${1:-${DEFAULT_APP_DIR}}"
APP_USER="${2:-${SUDO_USER:-$(id -un)}}"
APP_GROUP="${3:-$(id -gn "${APP_USER}")}"
TEMPLATE="${SCRIPT_DIR}/robbo-obibok.service.in"
TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

case "${APP_DIR}" in
  /*) ;;
  *) echo "APP_DIR must be an absolute path: ${APP_DIR}" >&2; exit 2 ;;
esac

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Application directory does not exist: ${APP_DIR}" >&2
  exit 2
fi
if [[ ! -f "${APP_DIR}/.env" ]]; then
  echo "Missing ${APP_DIR}/.env; create it with DISCORD_BOT_TOKEN before installing." >&2
  exit 2
fi
if [[ ! -x "${APP_DIR}/venv/bin/python3" ]]; then
  echo "Missing executable ${APP_DIR}/venv/bin/python3; run make install first." >&2
  exit 2
fi

tmp_unit="$(mktemp)"
trap 'rm -f "${tmp_unit}"' EXIT
sed \
  -e "s|@APP_DIR@|${APP_DIR}|g" \
  -e "s|@APP_USER@|${APP_USER}|g" \
  -e "s|@APP_GROUP@|${APP_GROUP}|g" \
  "${TEMPLATE}" > "${tmp_unit}"

install -o root -g root -m 0644 "${tmp_unit}" "${TARGET}"
systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}.service"
echo "Installed and started ${SERVICE_NAME}.service for ${APP_USER}:${APP_GROUP}."
