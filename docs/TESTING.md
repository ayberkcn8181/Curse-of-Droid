# Testing and baseline

Before modifying code, main `dea8ffc` passed **92 tests**, including two Widgets GUI tests, on Linux,
Python 3.12.14 and PySide6 6.12.0. Statement coverage was **1465/2237 = 65.49%** (terminal rounded 65%).
CLI help/version also exited 0. This is a measured baseline, not a target or branch-coverage figure.

```sh
python -m pip install -e '.[gui,dev]' pytest-cov
QT_QPA_PLATFORM=offscreen python -m pytest -q --cov=curseofdroid --cov-report=term-missing
python -m curseofdroid.cli --help
python -m curseofdroid.cli --version
```

Existing tests cover fixture parsing, detection with injected runners, provider parsing, vendor flows,
flash guard/planning/execution and Widgets typed consent. Network/download code, the CLI, worker failure
paths, settings, QML, frozen GUI and real hardware have important coverage gaps.

All automated device tests must use injected runners. Never run destructive commands against real
phones in CI. GUI tests use offscreen rendering. Native system-theme integration, GPU rendering and
actual USB transitions need separate manual results. Cross-platform historical CI success does not
establish that a newly changed build passed on those platforms.

Hardware matrix to record before future installation testing:

| Device / variant | OS + host | Transport | Read-only probes | Backup confirmed | Reviewed exact write procedure | Result |
| --- | --- | --- | --- | --- | --- | --- |
| No hardware in development environment | Linux container | None | Not performed | N/A | Not authorized | Untested |

Coverage thresholds should start near the measured baseline and increase after adding meaningful tests.
Use controlled HTTP responses for integrity/resume cases and queued Qt integration tests for workers.

## QML slice validation

`tests/test_qml.py` adds real engine rendering and mouse/keyboard events, controlled ADB/fastboot runners
through the real detection parser, multi-device selection, disconnect/unknown/unauthorized/error states,
worker completion/responsiveness, shutdown deferral, tool setup, live system-theme notifications, settings
restoration in a new Python process, semantic contrast and retained Widgets routing.

```
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m pytest -q \
  --cov=curseofdroid --cov-report=term --cov-report=json:coverage.json --cov-fail-under=65
110 passed in 3.12s; statement coverage 1772/2625 = 67.50%
```

The threshold is 65%, aligned with the measured baseline. Coverage includes screenshot/entry-point code
not exercised by unit tests; it does not measure QML line coverage. Unit/integration tests do not access a
physical device. CI now renders QML without USB probes and uploads coverage XML for each matrix job.

`python -m build --wheel --no-isolation` succeeded; package inspection includes QML and SVG assets.
`python -m compileall -q curseofdroid` and `git diff --check` passed.
The source GUI `--smoke-test` loads and renders QML with USB probing disabled.

A real `install_platform_tools()` attempt in the development environment failed with
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`. No TLS bypass was applied.
Real USB device discovery, flashing, native Windows/macOS integration and packaged GPU behavior remain
untested. Screenshot evidence shows the actual no-tools/no-device state rather than a fixture device.

The first frozen GUI run exposed a missing QtQuick/QtOpenGL dependency; the packaging configuration now
collects QtQuick explicitly and retains QtOpenGL. The rebuilt Linux GUI `--smoke-test` exited 0 with empty stderr/stdout, and the frozen CLI help/version exited 0.
Deterministic engine teardown also fixes shutdown-time null context warnings. Both failures received
regression coverage (source entry-point subprocess smoke plus frozen GUI validation).

## QML catalog slice

See [QML_CATALOG.md](QML_CATALOG.md) for the 32 additional controlled provider/Qt cases, screenshot
provenance and cancellation limits. On the UI-based catalog branch, **142 tests passed**, with
**1997/2901 covered statements (68.84%)**. Wheel asset inclusion, source smoke, clean isolated frozen
Linux GUI smoke, CLI help/version and compile/diff checks passed. Other native release builds are
not certified by these results. No physical device was used and no destructive command was executed.

GUI modules share one session QApplication. Dashboard owns its Catalog receivers and defaults to
application ownership, preventing loss of receiver ownership while a worker is still active. The GC
regression explicitly drops the caller reference during a blocked provider request and verifies delivery.
Earlier Windows CI heads had intermittent native access violations; see the PR for exact-head CI results.
The precise native fault was not established from the available Python-only crash trace.


## Read-only installation preview

`python -m pytest tests/test_qml_installation.py -q` exercises real local hashes, shared planners and
Qt worker/QML events with controlled device profiles. Preview tests forbid transport/Executor calls.
They cover cancellation and late-result races, input/device invalidation, 64-bit progress values,
duplicate serials, responsive GUI/close handling and dark/light rendering at both supported window sizes.
`python -m curseofdroid.gui.capture --pages install --output docs/screenshots/install-preview` records
actual application windows; see [the preview guide](QML_INSTALL_PREVIEW.md) for state and scope.


## Bounded ROM ZIP metadata

`python -m pytest tests/test_package_limits.py tests/test_qml_installation.py -q` covers bounded
classic/ZIP64 directories, stored/deflated metadata, malformed headers/counts, forged metadata sizes/CRCs,
canonical names, resource limits, cancellation, and metadata-to-plan identity binding. The virtual large-offset
case checks ZIP64 offsets above 4 GiB without allocating a physical 4-GiB file. CLI and Widgets regressions
verify ordinary planning errors and stale-action clearing. See [package inspection](PACKAGE_INSPECTION.md).
