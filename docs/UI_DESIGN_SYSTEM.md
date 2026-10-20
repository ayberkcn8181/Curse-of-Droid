# QML design system (first working slice)

One QML tree serves light, dark and system modes. Semantic colors live in `gui/theme.py`, including
preview palettes; pages do not embed theme hex values. Purple is the default accent; blue and teal
are validated alternatives. Brand SVGs are original project artwork and retain the brand purple.
The existing PySide6 dependency supplies Qt Quick, Controls and SVG rendering; pytest-cov is a new
**development-only** MIT-licensed dependency. All new project source/artwork remains GPL-3.0-or-later.

## Tokens and interaction

- Background / surface / elevated, primary / secondary text, border, accent / hover / on-accent,
  selection, success / warning / error are semantic roles.
- Dark background #0D0F17; light background #F6F7FB. Filled accent #7048CF was chosen so white labels
  meet 4.5:1 contrast in both themes. Semantic status text is also checked against all three surfaces.
- Cards use 15px corners, buttons 9px, 16–24px section spacing; body text is normally 14px.
- Components: AppButton, AppComboBox, Toggle, UiText, InfoCard, StatCard, DeviceCard, FieldRow,
  PageHeader, EmptyState, StatusBadge, ActivityList, ThemeSelector, NavigationSidebar, TopToolbar,
  NotificationToast and NotificationCenter.
- Tab focus, visible focus outlines, accessible labels, Ctrl+1 / Ctrl+2 / Ctrl+, and F5 shortcuts.
- Sidebar collapses; central pages scroll and use responsive grids. Default window fits the available
  desktop, with a 920×680 minimum. The tested baseline includes 1260×900 and 920×680 at 100% scale.
- Preferences: system/light/dark, accent, 100/115/130% UI scale, motion on/off. Changes sync via QSettings
  to the platform data directory (or CURSEOFDROID_HOME). Save errors produce a notification.
- System preference uses Qt styleHints.colorSchemeChanged. Unknown/unsupported preference falls back
  to light. Explicit light/dark override system changes. Theme and palette are restored before QML loads.
- Motion can be explicitly disabled. Automatic OS reduced-motion integration is not implemented yet.

## Real functionality and migration boundary

Dashboard displays actual tools discovery, device selection/profile and session events. Counts are from
backend state; an undiscovered device count is shown as “—”. Unknown properties stay unknown; storage
is explicitly not reported. The provider count is the real registry count, not compatible ROM results.
Discovery/tool installation run in workers. No device commands or fake data are implemented in QML.

Dashboard, My device, Activity & logs, Settings, ROM Library and Recovery Manager are functioning QML
pages. Remaining QML navigation entries are explicitly disabled pending migration. ROM/recovery discovery and installation quick actions
open the preserved Widgets workflow with the chosen device. This first UI slice combines theme,
components, shell and Dashboard because they are required together to demonstrate a working application.
The audited legacy flash safety issues still require separate PRs before expanding automated installation.

## Visual evidence

Screenshots in `screenshots/` are actual `QQuickWindow.grabWindow()` captures on Linux using offscreen,
software rendering, without device injection. `capture.json` records the actual backend state and Qt
version. Both themes and Settings/Dashboard at two sizes are included. No physical phone or native
Windows/macOS desktop was available. These captures do not certify GPU/native theme behavior.

Run `python -m curseofdroid.gui.capture` to regenerate captures. It uses temporary preferences and the
real backend; it does not modify the user's theme preferences. Qt text/keyboard/render tests supplement
manual inspection, but are not comprehensive screen-reader or WCAG compliance certification.

## Remaining work

Dedicated QML download/wizard/advanced pages, persistent operation history, support bundles,
Turkish/English translation catalogs (qsTr hooks are present), language selection, full native dialogs,
automatic OS motion preferences and extended high-DPI/accessibility/native-platform QA remain open.
