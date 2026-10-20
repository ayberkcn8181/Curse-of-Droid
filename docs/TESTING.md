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
