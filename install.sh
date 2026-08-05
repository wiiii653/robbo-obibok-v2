#!/usr/bin/env bash
# Robbo Obibok v2 — installer "od zera do działającego bota"
#
# Dla lamerów (i nie tylko): wykrywa dystrybucję, instaluje zależności
# systemowe, robi venv, pyta o token Discorda, stawia systemd i opcjonalnie
# ściąga archiwa muzyczne.
#
# Użycie:
#   ./install.sh                 # pełna instalacja (bez archiwów)
#   ./install.sh --archives      # + ściąga archiwa (hvsc, asma, ay, ym, tiny, kgen)
#   ./install.sh --no-systemd    # nie dotykaj systemd (tylko venv + deps)
#   ./install.sh --help
#
# Zmienne środowiskowe:
#   DISCORD_BOT_TOKEN=xxx        # token z https://discord.com/developers/applications
#   ROBBO_ARCHIVES="hvsc asma"   # wybór archiwów przy --archives
#   ROBBO_SKIP_DEPENDS=1         # nie instaluj pakietów systemowych (masz je)
set -euo pipefail

# ── kolory (jeśli TTY) ────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_OFF=""
fi
ok()   { echo "${C_GREEN}✓${C_OFF} $*"; }
warn() { echo "${C_YELLOW}!${C_OFF} $*"; }
fail() { echo "${C_RED}✗${C_OFF} $*"; exit 1; }
info() { echo "${C_BOLD}→${C_OFF} $*"; }

# ── argumenty ─────────────────────────────────────────────────────────
WITH_ARCHIVES=0
WITH_SYSTEMD=1
for arg in "$@"; do
  case "$arg" in
    --archives) WITH_ARCHIVES=1 ;;
    --no-systemd) WITH_SYSTEMD=0 ;;
    --help|-h)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) fail "nieznany argument: $arg (patrz ./install.sh --help)" ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── wymagania wstępne ─────────────────────────────────────────────────
command -v python3 >/dev/null 2>&1 || fail "brak python3 — zainstaluj najpierw"
command -v curl   >/dev/null 2>&1 || fail "brak curl — zainstaluj najpierw"

PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [[ "$PY_MAJOR" -lt 3 || "$PY_MINOR" -lt 11 ]]; then
  fail "potrzebny Python >= 3.11 (masz $PY_MAJOR.$PY_MINOR) — zaktualizuj system"
fi

# ── instalacja zależności systemowych ─────────────────────────────────
if [[ "${ROBBO_SKIP_DEPENDS:-0}" != "1" ]]; then
  info "Sprawdzam zależności systemowe..."

  # pakiet(y) wymagane do rozpakowywania archiwów + odtwarzania
  DEPS_PY="python3-venv python3-pip"
  DEPS_AUD="audacious audacious-plugins ffmpeg pipewire-pulse gstreamer1.0-plugins-good sidplayfp"
  DEPS_7Z="p7zip-full"

  if command -v apt-get >/dev/null 2>&1; then
    info "Debian/Ubuntu: apt-get"
    if [[ "$(id -u)" -ne 0 ]]; then
      warn "sudo apt-get install wymaga uprawnień — pytam..."
    fi
    sudo apt-get update -qq
    sudo apt-get install -y $DEPS_PY $DEPS_AUD $DEPS_7Z
  elif command -v dnf >/dev/null 2>&1; then
    info "Fedora/RHEL: dnf"
    sudo dnf install -y python3 python3-virtualenv audacious audacious-plugins \
      ffmpeg pipewire-utils gstreamer1-plugins-good sidplayfp p7zip p7zip-plugins
  elif command -v pacman >/dev/null 2>&1; then
    info "Arch: pacman"
    sudo pacman -S --needed --noconfirm python python-virtualenv \
      audacious audacious-plugins ffmpeg pipewire gst-plugins-good sidplayfp p7zip
  else
    warn "Nie rozpoznaję menedżera pakietów — pomijam instalację systemową."
    warn "Zainstaluj ręcznie: python3>=3.11, audacious+pliki, ffmpeg, pipewire, p7zip"
  fi
  ok "Zależności systemowe gotowe"
else
  info "Pomijam zależności systemowe (ROBBO_SKIP_DEPENDS=1)"
fi

# ── venv + deps Pythona ───────────────────────────────────────────────
if [[ ! -x "venv/bin/python3" ]]; then
  info "Tworzę venv..."
  python3 -m venv venv || fail "nie udało się utworzyć venv"
fi
info "Instaluję zależności Pythona (pip)..."
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -e ".[dev]" || fail "pip install -e '.[dev]' nie przeszedł"
ok "venv gotowy"

# ── token Discorda ────────────────────────────────────────────────────
if [[ -f ".env" ]] && grep -q "DISCORD_BOT_TOKEN=your-token-here" ".env" 2>/dev/null; then
  warn "Token w .env to placeholder — poproszę o właściwy."
  rm -f ".env"
fi

if [[ ! -f ".env" ]]; then
  if [[ -n "${DISCORD_BOT_TOKEN:-}" ]]; then
    printf 'DISCORD_BOT_TOKEN="%s"\n' "$DISCORD_BOT_TOKEN" > .env
    ok "Token wczytany z DISCORD_BOT_TOKEN"
  else
    info "Podaj token bota Discorda (https://discord.com/developers/applications):"
    read -r -p "> " TOKEN_INPUT
    if [[ -z "$TOKEN_INPUT" ]]; then
      warn "Pusty token — zapisuję .env z placeholderem, uzupełnisz później."
      cp .env.example .env
    else
      printf 'DISCORD_BOT_TOKEN="%s"\n' "$TOKEN_INPUT" > .env
      ok "Token zapisany w .env"
    fi
  fi
  chmod 600 .env 2>/dev/null || true
fi

# ── systemd ───────────────────────────────────────────────────────────
if [[ "$WITH_SYSTEMD" == "1" ]]; then
  if [[ -f ".env" ]] && grep -q "your-token-here" ".env" 2>/dev/null; then
    warn "Token to placeholder — pomijam instalację systemd."
    warn "Uzupełnij .env i odpal: sudo deploy/install-systemd.sh"
  elif command -v systemctl >/dev/null 2>&1; then
    info "Instaluję serwis systemd..."
    sudo deploy/install-systemd.sh "$SCRIPT_DIR" || warn "install-systemd.sh zwrócił błąd"
    ok "Serwis robbo-obibok zainstalowany i wystartowany"
  else
    warn "Brak systemd — bot odpalasz ręcznie: ./run_bot.sh"
  fi
else
  info "Pomijam systemd (--no-systemd). Start ręczny: ./run_bot.sh"
fi

# ── archiwa ───────────────────────────────────────────────────────────
if [[ "$WITH_ARCHIVES" == "1" ]]; then
  ARCHIVES_DEFAULT="hvsc asma ay ym tiny kgen"
  ARCHIVES="${ROBBO_ARCHIVES:-$ARCHIVES_DEFAULT}"
  info "Ściągam archiwa: $ARCHIVES (pomijam modarchive — to GB!, odpal osobno)"
  if [[ ! -x "venv/bin/python3" ]]; then
    fail "brak venv — coś poszło nie tak wyżej"
  fi
  for a in $ARCHIVES; do
    info "Archiwum: $a"
    ./venv/bin/python3 scripts/fetch_archives.py "$a" --build-index \
      || warn "fetch_archives.py $a — błąd (może brak 7z albo sieć)"
  done
  ok "Archiwa gotowe (modarchive: python3 scripts/fetch_archives.py modarchive)"
else
  info "Pomijam archiwa (dodaj --archives, żeby je ściągnąć)."
  info "Później: python3 scripts/fetch_archives.py all --check"
fi

# ── podsumowanie ──────────────────────────────────────────────────────
echo
echo "${C_GREEN}${C_BOLD}== Robbo Obibok v2 zainstalowany ==${C_OFF}"
echo "  start:   ${C_BOLD}./run_bot.sh${C_OFF}   (ręcznie)"
echo "  systemd: ${C_BOLD}sudo systemctl status robbo-obibok${C_OFF}"
echo "  logi:    ${C_BOLD}journalctl -u robbo-obibok -f${C_OFF}"
echo "  archiwa: ${C_BOLD}./venv/bin/python3 scripts/fetch_archives.py all --check${C_OFF}"
echo "  testy:   ${C_BOLD}make test${C_OFF}"
echo
info "Żeby bot widział kanał głosowy — wjedź na niego i wpisz !play. Las gra. 🌲"
