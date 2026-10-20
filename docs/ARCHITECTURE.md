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
