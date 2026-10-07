# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [2.0.0] - 2026-10-07

Pierwsze publiczne wydanie Robbo Obibok v2 — discordowego bota chiptune radio.

**Packaging & CI**
- Added packaging and dependency-audit checks to CI (ruff, pytest --cov, `python -m build`, pip-audit z udokumentowanym ignore).
- Added LICENSE (MIT), autor/licencja/URL-e w metadanych paczki.
- 10 kolekcji archiwum z indeksami budowanymi przez Makefile.

**Deployment**
- Added configurable systemd installation and service hardening (`deploy/`).
- `prestart.sh` jako `ExecStartPre` — ubija osierocone ffmpeg/bot przed startem usługi.

**Runtime & reliability**
- Durable, locked persistence with corruption backups and schema-versioned records.
- Atomic cache writes (`save_json_atomic`) in all index builders.
- Silence watchdog self-healing a dead audacious stream.
- Voice: throttle + backoff reconnectów, żeby nie wpaść w spiralę rate-limitu Discorda.
- Party: retry ledger dla imprez, które miały linki, ale 0 pobrań.
- Learned lengths DB + świeże HVSC Songlengths przy każdym update.

**Security**
- Remote-download allowlisting, redirect validation i odrzucanie adresów prywatnych.
- Bezpieczne rozpakowywanie ZIP-ów z modarchive (ochrona przed traversalem + odrzucanie śmieci).

**Diagnostics**
- Runtime health diagnostics i opt-in testy integracyjne z hostem.
