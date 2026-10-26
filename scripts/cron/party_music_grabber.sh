#!/usr/bin/env bash
# Party Music Grabber — cron wrapper (niedziela 06:00).
# Uruchamia scripts/party_music_grabber.py, a JESLI przybylo trackow, restartuje bota,
# zeby zagral nowa kolekcje bez czekania na reczny restart.
#
# OKNO 45 dni (domyslne) zamiast 10: cron jest COTYGODNIOWY, wiec party,
# ktore raz padnie na scenie.org, ma 6 niedziel na nadrobienie zanim
# wypadnie z okna. Dodatkowo rejestr party_retry.json ponawia party z
# linkami ale 0 pobranych NAWET poza oknem (az do --retry-max prob).
#
# UWAGA na TMPDIR: rozpakowywanie archiwow NIE korzysta z TMPDIR — pythonowy
# _safe_tempdir() uzywa <repo>/var/tmp, bo is_junk_path() odrzuca kazda sciezke
# z katalogiem zaczynajacym sie od kropki, a i ~/.cache, i ~/.hermes ja maja.
# (Zmierzone 2026-10-26: cron z TMPDIR=~/.cache/... pobieral pliki i wyrzucal je
# po cichu jako "smieci" — 0 zapisanych przy 48 pobranych.)
set -u

ROOT=/home/boruta/robbo-obibok-v2
CACHE="$ROOT/party_cache_local.json"
ENVFILE=/home/boruta/.hermes/.env

export TMPDIR="${TMPDIR:-/home/boruta/.cache/party_grabber_tmp}"
mkdir -p "$TMPDIR"

count_tracks() {
  python3 - "$CACHE" <<'PY'
import json
import sys

try:
    print(int(json.load(open(sys.argv[1]))["total"]))
except Exception:
    print(0)
PY
}

restart_bot() {
  local pw pid
  pw=$(grep -m1 '^SUDO_PASSWORD=' "$ENVFILE" 2>/dev/null | cut -d= -f2- | tr -d '"\047')
  if [ -z "$pw" ]; then
    echo "!! brak SUDO_PASSWORD w $ENVFILE — bot NIE zrestartowany, zrob to recznie"
    return 1
  fi
  printf '%s\n' "$pw" | sudo -S systemctl restart robbo-obibok >/dev/null 2>&1
  unset pw
  sleep 6
  if systemctl is-active --quiet robbo-obibok; then
    pid=$(systemctl show -p MainPID --value robbo-obibok)
    echo "== Bot zrestartowany — active, PID $pid"
  else
    echo "!! Restart bota NIE wyszedl — sprawdz: journalctl -u robbo-obibok -n 40"
    return 1
  fi
}

# --force-restart: wymus restart nawet bez nowych trackow (do testow)
FORCE=0
[ "${1:-}" = "--force-restart" ] && FORCE=1

BEFORE=$(count_tracks)
echo "== Trackow przed: $BEFORE"

nice -n 10 python3 "$ROOT/scripts/party_music_grabber.py" --top 5
rc=$?

AFTER=$(count_tracks)
echo "== Trackow po:    $AFTER"

if [ "$AFTER" -gt "$BEFORE" ] || [ "$FORCE" -eq 1 ]; then
  [ "$FORCE" -eq 1 ] && echo "== Wymuszony restart (--force-restart)"
  [ "$AFTER" -gt "$BEFORE" ] && echo "== Nowe tracki: $BEFORE -> $AFTER (+$((AFTER-BEFORE)))"
  restart_bot || rc=1
else
  echo "== Bez nowych trackow — bot nie wymaga restartu (gra dalej to samo)"
fi

exit $rc
