# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

## [2.1.0] - 2026-10-28

Reliability release: the radio no longer goes silent after a lost voice session,
and the party grabber no longer fails quietly.

**Features**
- Playback resumes the last played collection after a restart. `var/queues/<guild>.json`
  already carried `collection_mode`, but nothing read it back, so every restart fell
  through to the default collection. An explicit collection argument still wins over
  the saved one, and the collection is validated against the archive on disk.

**Voice recovery**
- The health watchdog re-arms itself instead of giving up for good. After three failed
  voice attempts it used to discard the pending reconnect, stop the engine and stay
  silent until a human restarted the service. A guild whose budget was exhausted is now
  retried after `VOICE_RECONNECT_REARM_DELAY` (300 s), gated on a real listener being
  in the channel.
- `resolve_voice_channel()` falls back to the last connected channel and then to the
  configured auto-start channel name. Stopping the engine blanks
  `state.voice_channel_id`, which previously left the watchdog with nothing to join
  (`voice_channel_id None not found or invalid`).
- `PlaybackCog.resume_after_rearm()` restarts the queue via `start_radio` before
  connecting — rebuilding only the transport left the bot connected but silent.

**Party music grabber**
- Bypass the Cloudflare wall and the dot-directory junk filter. Demozoo rejects
  `curl/*`, browser strings and empty user agents with HTTP 403; a declared project
  token (`robbo-grabber/1.0 (+repo-url)`) gets JSON. Archives are now unpacked into
  `<repo>/var/tmp`, because `is_junk_path()` rejects any path containing a
  dot-prefixed component and `TMPDIR` pointed into a dotted cache directory — every
  extracted file was silently classified as junk and `process_production()` returned
  `(0, 0, 0)` without an error.
- Cache the party list and cap pagination. The Demozoo API ignores every filter and
  always reports 5563 parties in alphabetical order, so a run has to walk ~56 pages
  before it can filter by date; one run stalled on page 40 for seven minutes. The list
  is now cached for 12 h, pagination is capped at `MAX_LIST_PAGES=120`, an incomplete
  list prints `NIEKOMPLETNA` and never overwrites the cache, and `--refresh-list`
  forces a full walk.
- Cap the retry counter on every increment path. Only the download branch honoured
  `--retry-max`; the "no details" branch incremented forever, leaving entries with
  four and six attempts against a limit of four.
- Deduplicate by content, not by the base name. `dedupe_path()` compared sizes only for
  the bare name and accepted `(2)`, `(3)`… blindly, so two different tracks of equal
  size kept multiplying copies (36 MB of duplicates). Candidates are now compared by
  sha256 via `_same_bytes()`, with `tests/test_party_grabber_dedupe.py` covering it.

**Deployment**
- The cron wrapper is versioned in the repository
  (`scripts/cron/party_music_grabber.sh`); `~/.hermes/scripts/` keeps only a three-line
  `exec` shim. After a grab it counts the tracks, runs `--top 5`, and restarts
  `robbo-obibok` through `sudo -S` only when the collection actually grew.

**Docs**
- Documented the two-stage volume chain and the Audacious master volume.
- Added SPDX headers to the compiled plugins and clarified their licensing.

## [2.0.0] - 2026-10-07

Pierwsze publiczne wydanie Robbo Obibok v2 — discordowego bota chiptune radio.

**Packaging & CI**
- Added packaging and dependency-audit checks to CI (ruff, pytest --cov, `python -m build`, pip-audit z udokumentowanym ignore).
- Added LICENSE (MIT), autor/licencja/URL-e w metadanych paczki.
- 10 kolekcji archiwum z indeksami budowanymi przez `make build-indexes`.

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
