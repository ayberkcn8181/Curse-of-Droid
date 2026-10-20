# Repository audit and development roadmap

Audit date: 2026-10-20. Audited main: `dea8ffcf65a8f4c11eb8e75322e5d799db0aff94` (0.1.0a5).
This records code inspection and executed tests, not a claim of production readiness.

## Baseline (before code changes)

Linux, Python 3.12.14, PySide6 6.12.0, pytest 9.1.1:

```
QT_QPA_PLATFORM=offscreen python -m pytest -q --cov=curseofdroid --cov-report=term
92 passed in 3.02s
TOTAL: 2237 statements, 772 missed, 65% (rounded statement coverage)
```

`python -m curseofdroid.cli --help` and `--version` exited 0 (0.1.0a5).
Coverage is not branch coverage. GUI tests are included, not skipped. No real phone was connected;
no flash, unlock, reboot or erase operation was executed. Tests inject transports/catalog responses.

At inspection, GitHub reported no issues or PRs, release v0.1.0a5, and successful CI and release
runs on the audited SHA. Historical success is not validation of future changes:
[CI](https://github.com/ayberkcn8181/Curse-of-Droid/actions/runs/38245898102),
[Release](https://github.com/ayberkcn8181/Curse-of-Droid/actions/runs/38245898009).

## Implemented, as found in code

- argparse CLI: tools, drivers, detect, find, download, install, unlock, gsi; shared Python backend.
- ADB/fastboot listing, per-serial read-only probes, unauthorized/offline states, getprop/getvar parsing,
  tristate device properties, battery reads, A-only/A/B/dynamic/Treble profile fields.
- 19 ROM project providers plus TWRP and OrangeFox; Lineage recovery artifacts when supplied by builds;
  TrebleDroid GSI discovery and xz unpacking. Alias lookups isolate provider failures. GrapheneOS/CalyxOS
  advertise their own installers; historical projects are labeled. Google Play + Lineage wiki metadata.
- HTTPS with certifi, disk caching, partial-download Range requests, size and available hash checks,
  atomic rename after verification. Absence of hashes does **not** establish cryptographic verification.
- Recovery-sideload and GSI plans, dry runs, command guard, partition allowlist, firmware/relock refusals,
  explicit consent for data-loss/system-write steps; vendor-specific automated or guided unlock flows.
- Four-page Qt Widgets GUI over the same backend, QRunnable workers and queued consent bridge.
- PyInstaller folder archives, separate CLI/GUI, release checksums, Linux/Windows/macOS GitHub matrices.

## Confirmed gaps and bugs

| Priority | Evidence | Finding / required follow-up |
| --- | --- | --- |
| P0 | `flash/planner.py:preflight`, `plan_gsi_install` | Unknown bootloader state is permitted. Planning has no trusted artifact/hash provenance requirement. GSI image existence/Treble/ABI checks are incomplete. Add fail-closed manifests and regression tests before expanding automatic installation. |
| P0 | `flash/executor.py:run` | No fresh profile/identity/partition revalidation immediately before writes; serial can be None. A static command allowlist is not device-specific validation. |
| P0 | `flash/guard.py:check_command` | ADB shell validation is a blocklist for dd/mkfs patterns, not an exhaustive read/write allowlist. Other arbitrary shell instructions pass. Keep the new QML bridge read-only. |
| P1 | `platform/net.py:verify`, GUI download callback | Missing hashes succeeds; GUI says “Verified” even for size-only downloads. Checksums include MD5/SHA1; signatures are not verified. |
| P1 | `platform/net.py:download` | Resume does not validate Content-Range/ETag/Last-Modified; no disk-space budget, bounded retries or cancellation. Remote filenames need boundary checks at destination construction. |
| P1 | `gui/app.py:show_devices`, `make_plan` | First device is implicitly selected. Previously generated plan and unlock state can become stale after device changes. |
| P1 | `gui/bridge.py:_round_trip` | Consent waits indefinitely; GUI shutdown during an active operation needs lifecycle handling. |
| P1 | `packaging/build.py:QT_UNUSED` | QtQml/QtQuick/QtSvg/QtNetwork are excluded; QML migration requires explicit data collection and frozen GUI startup tests. |
| P2 | README / DESIGN vs implementation | Builder, generic workflow/plugin engine, Samsung flashing, signature verification and full download manager are planned, not implemented. CLI uses argparse, not Typer/rich. Tool bootstrap is HTTPS + ZIP CRC, not publisher checksum pinned. |
| P2 | tests and CI | No measured threshold, dependency audit, frozen GUI smoke or screenshot regression suite. CI mixes deterministic tests with external downloads; `detect || true` hides all detection failures. |

## Risks requiring verification (not confirmed exploits)

- Archive extraction trust boundaries, symlinks, malformed archive metadata and decompression/disk budgets.
- Unknown transport return codes may appear as empty detection results; test each failure mode explicitly.
- Codename collisions, device variants, firmware requirements, active slots and recovery partition choice
  require device-specific rules; codename equality alone is insufficient.
- Provider service drift, redirects to HTTP, rate limits and stale catalogs need controlled HTTP tests.
- Packaged Qt plugins, certificates and platform theme detection require native OS validation.
- Accessibility, text contrast, high DPI, multi-monitor behavior and modest-hardware performance need measurements.

## Dependencies and external services

Python >=3.10; certifi (MPL-2.0), PyYAML (MIT); optional PySide6/Qt (LGPL/GPL/commercial distribution terms).
Project remains GPL-3.0-or-later. QML can reuse PySide6 without adding runtime dependencies. New icons
should be original GPL-compatible SVGs. Preserve Qt/license notices in distributions; no new artwork or
third-party component license may be assumed.

Google platform-tools/USB driver downloads, Google Play CSV, Lineage wiki/download APIs, GitHub raw/API,
ROM project APIs, TWRP, OrangeFox, SourceForge and vendor unlock portals are external dependencies.
Unit tests should never require those services or a real device.

## Migration and ordered work

1. **Audit PR:** this roadmap, architecture, testing baseline and device support documentation; base main.
2. **First UI PR:** one cohesive QML design-system/shell/Dashboard slice, semantic dark/light tokens,
   light/dark/system persisted preferences and live system notifications, reusable components, real
   background detection/tool setup, explicit device selection, activity/errors, real offscreen captures,
   QML packaging and GUI regression tests. Base the audit branch (stacked, no automatic merges).
   Keep the existing Widgets workflow explicitly reachable during migration; do not duplicate flash code.
3. **Independent safety PRs:** guard allowlists, trusted verification manifests, fresh device/slot checks,
   download/resume hardening; each confirmed issue receives a focused regression test.
4. **Device/catalog/recovery PRs:** complete QML pages backed by existing providers, failure isolation,
   verified device-specific methods. Do not enable placeholder install buttons.
5. **Wizard/download/log PRs:** cancellation/lifecycle, reviewed installation plans, immutable identity,
   redacted exports and safe download queue.
6. **Localization/CI/packaging PRs:** Turkish/English translations, offline cross-platform checks,
   dependency audit, frozen GUI execution and native hardware test matrix.

Each stage has its own branch and PR with executed test results, important changed files, screenshots
for UI, remaining gaps, and actual platform status. Dependent PRs explicitly name their base. No PR
is merged without the owner's approval. A mocked test or offscreen capture is not real hardware validation.
