# Stable controller connections

Native macOS/Python 3.10 CI on PR #11 head `084e2f4` reported missing DownloadManager properties/signals
and a close guard accepting closure during an active transfer. This stage is separate from ZIP parsing.
The same commit's PR-triggered macOS job passed; the push job's failure remains recorded rather than rerun.

Qt diagnostics reproduce two runtime-generated receiver signatures on all platforms tested locally:
`enqueue(PyObject)` on DownloadManager and `_system_changed(Qt::ColorScheme)` on ThemeManager.
The former lacked a Slot declaration. The latter had a no-argument declaration but a variadic Python
signature, causing PySide to extend its metadata when connected to the native enum signal.

DownloadManager now declares its object receiver before connections are made. Its existing Build/type,
HTTPS, checksum, filename and provenance checks remain mandatory; supplying a plain QML object cannot
start a transfer. The theme callback now has a genuinely zero-argument Python signature, allowing Qt to
discard the native signal argument without registering another per-instance method. System notifications
and no-argument controlled hints remain supported.

A fresh-process regression enables Qt's missing-Slot diagnostics and checks the actual QML application,
native system-theme signal delivery, Downloads navigation and active-operation close refusal. It fails
before the fix on both dynamic registrations and passes after it. Existing download/catalog/theme tests
remain enabled. The observed native failure is consistent with unstable per-instance metadata; the exact
Qt cache internals behind that intermittent failure have not been proven.

This does not change layout, theme palettes, persisted settings, network integrity policy or device
execution. Existing real dark/light captures remain applicable. Native CI results and executed counts are
recorded in the PR. Physical devices, native GPU/display behavior and the separate installation safety
follow-ups remain unvalidated.

Reference: [Qt for Python signals and slots](https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html).
