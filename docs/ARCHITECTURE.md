# Architecture

The CLI (`curseofdroid/cli.py`) and Widgets app (`gui/app.py` at the audit baseline) call the same
`device`, `transport`, `catalog`, `vendors`, `flash` and `platform` modules. Transport execution uses
argument arrays with injectable runners. The flash executor validates plans, asks the UI for consent
and executes steps; its remaining safety gaps are listed in DEVELOPMENT_ROADMAP.md.

QML migration boundary: QML presentation → QObject view models → existing Python services.
No shell-command slot, flash primitive or second backend belongs in QML. Blocking discovery and
network work must use workers with queued QObject receivers. Selected-device state must be explicit;
unknown values remain unknown. The legacy Widgets workflow stays available until equivalent QML
pages and backend safety work are reviewed. Theme preferences are presentation-only.

## First QML slice

`gui/app.py` owns QApplication, QQmlApplicationEngine and QObject lifetimes; the prior app is preserved
in `gui/widgets.py`. `MainWindow` remains importable from `gui.app` for compatibility.
`gui/dashboard.py` exposes read-only discovery state, redacted device choices, provider count and session
activity. It calls the existing `detect`, `find_tools` and `install_platform_tools`; no mock data exists
in the runtime. Jobs use bound QObject slots for queued results and keep the UI thread free.
The shell refuses to close while its own job is active; these read-only jobs finish or time out rather
than being unsafely terminated. Legacy installer shutdown/cancellation remains a separate audit issue.

Multiple devices require a selection. Refresh clears stale profiles; a previously chosen serial is
retained internally only to restore the same choice if still present. Raw serials are not exposed by
the device model. Opening an existing workflow creates a Widgets window with the selected Detected
object and reuses the original backend/guards; no flash executor is exposed directly to QML.

`gui/theme.py` owns validated QSettings preferences and semantic palettes. Runtime creates it before
loading QML. System mode watches Qt colorSchemeChanged; unsupported/unknown schemes fall back to light.
The QML component tree is shared by all themes. No runtime dependency was added beyond existing PySide6.
