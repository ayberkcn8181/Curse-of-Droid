# Read-only transport failures

Confirmed on audit baseline `a3c871b`: a controlled runner returning exit 1 and `permission denied`
caused both `Adb.devices()` and `Fastboot.devices()` to return `[]`. Failed property probes likewise
looked like empty properties. This is not evidence that no phone is connected.

## Change

`Tool.read()` checks status and raises `TransportError` with the tool/operation/exit code and a short
USB authorization/permissions/driver hint. It does not include raw output, command arguments or serials.
ADB device/property/shell probes and fastboot device/getvar probes use it. Successful empty lists remain
valid. Battery information is optional: an unsupported battery command leaves `battery_percent=None`
while preserving a successfully identified profile.

The CLI reports transport errors to stderr with exit **2**, distinct from successful discovery with no
phone (exit **1**). Existing GUI workers already report exceptions; the QML view model in UI PR #2 uses
that same worker path. `Tool.run()`, flash execution, sideload exit-code handling, consent and guards are
unchanged. No real device command was executed in testing.

## Validation

On Linux / Python 3.12.14 / PySide6 6.12.0, based on the audit branch rather than the UI branch:

```
QT_QPA_PLATFORM=offscreen python -m pytest -q --cov=curseofdroid --cov-report=term
104 passed in 0.82s; 1577/2254 covered statements = 69.96%
```

Twelve added cases cover six read methods, ADB/fastboot detection failures, optional battery failure,
valid empty discovery and distinct CLI exits. CLI help/version and `git diff --check` also passed.
All runners are controlled; no test uses real USB hardware or destructive commands.

## Limitations

A required probe failure stops the scan. Per-device partial-result recovery, timeout classification,
native driver diagnosis and localized error messages remain follow-ups. Unsupported fastboot variables
now produce an explicit read failure instead of being silently interpreted as absent. The P0 artifact
verification, device identity and flash-guard findings from the audit are not fixed by this change.
