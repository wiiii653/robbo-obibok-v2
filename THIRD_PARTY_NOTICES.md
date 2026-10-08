# Third-party notices

Robbo Obibok v2 is released under the **MIT License** (see [`LICENSE`](LICENSE)).

That license covers **only the original source code of this project** — everything
under `src/`, `scripts/`, `tests/`, `deploy/`, the build files and the documentation.

The repository additionally **vendors** third-party components under `plugins/`,
used to build the optional chiptune plugins (SNDH / SAP / YM). Those components
keep their own licenses and are **not** covered by this project's MIT license.

## Vendored components

| Component | Location | License | Copyright |
|---|---|---|---|
| **SC68** suite — `as68`, `desa68`, `file68`, `info68`, `libsc68`, `sc68`, `sourcer68`, `unice68`, `sc68-doc` | `plugins/sndh/vendor_sc68/` | **GNU GPL v3.0** (copyleft) | Benjamin Gerard and contributors |
| **ASAP** 8.0.0 — Atari SAP player | `plugins/sap/vendor/asap-8.0.0/` | **GNU GPL v2.0** (copyleft) | Piotr Fusik and contributors |
| **StSound** library — YM chiptune player | `plugins/ym/vendor/stsound/` | **MIT** | Arnaud Carré (c) 2021 |

Full license texts are kept next to each component (`COPYING` for the GPL
components, `LICENSE` for StSound) exactly as distributed upstream.

## What this means in practice

- Using, modifying and redistributing the **project's own code** is governed by MIT.
- The vendored **SC68** and **ASAP** sources are **GPL (v3 / v2)**. If you
  redistribute the repository or ship **compiled plugin binaries** built from
  them, you must comply with the corresponding GPL terms (source availability,
  license notice, copyleft on the derived plugin).
- **StSound** is MIT and therefore compatible with this project's license.
- The **published release artifacts** (`sdist` / `wheel` attached to a GitHub
  Release) contain **no vendored plugin sources** — the packaging only includes
  the `src/` package. Building the optional plugins from source is a separate,
  opt-in step (`plugins/*/build.sh`).
- Compiled plugin binaries (`plugins/*/*.so`) and their build directories are
  intentionally **not tracked** in git.

If a fully permissive distribution is required, the vendored GPL plugins must be
removed or replaced — the core bot does not link against them.
