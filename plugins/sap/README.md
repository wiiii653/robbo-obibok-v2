# ASAP input plugin for Audacious 4.6.1

Native Audacious input plugin for Atari SAP files, built with ASAP 8.0.0.  It
handles SAP `TYPE A`, `B`, `C`, `D`, `E`, and `S`, including dual-POKEY/stereo
files. ASAP is compiled into `sap.so`; no GME 6502 playback stub is used.

## Build

```sh
./build.sh
```

This produces `sap.so` and the standalone `test_asap` renderer. The build
requires the Audacious 4.x development headers/libraries plus GCC/G++.

## Installation

Copy `sap.so` manually into the appropriate per-user or system Audacious input
plugin directory, then restart that Audacious instance. This project does not
perform installation or modify any Audacious configuration.

## Playback behavior

The plugin exposes `.sap` and validates the leading `SAP` magic. It renders all
SAP subsongs in order, then returns normally so Audacious advances to the next
playlist entry. `TIME` values are used per song; missing or non-positive values
are bounded to 180 seconds. This also bounds SAP headers marked `LOOP`, rather
than looping an entry forever. Seek positions are interpreted relative to the
concatenated subsongs.

ASAP produces signed 16-bit little-endian PCM in the file's native channel
count. Mono is duplicated for Audacious' stereo output; dual-POKEY stereo is
passed through.
