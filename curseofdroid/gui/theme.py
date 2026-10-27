"""Presentation preferences and semantic colors shared by QML and native Qt dialogs."""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from ..platform.paths import data_dir

PALETTES = {
    "dark": dict(background="#0D0F17", surface="#171A26", elevated="#202436", text="#F5F5FA",
                 secondary="#A1A1B5", border="#34384A", success="#4ADE80", warning="#FBBF24",
                 error="#FB7185", onAccent="#FFFFFF"),
    "light": dict(background="#F6F7FB", surface="#FFFFFF", elevated="#EAECF5", text="#181824",
                  secondary="#646477", border="#DDE0EA", success="#16703A", warning="#925200",
                  error="#BB2438", onAccent="#FFFFFF"),
}
# Filled buttons keep white-label contrast >=4.5:1 in both modes.
ACCENTS = {"purple": ("#7048CF", "#6440BC"), "blue": ("#2365BF", "#1956AA"),
           "teal": ("#087A70", "#00695F")}


class ThemeManager(QObject):
    changed = Signal()
    preferenceError = Signal(str)

    def __init__(self, settings: QSettings | None = None, hints=None, parent=None):
        super().__init__(parent)
        if settings is None:
            path = data_dir() / "preferences.ini"
            path.parent.mkdir(parents=True, exist_ok=True)
            settings = QSettings(str(path), QSettings.IniFormat)
        self.settings = settings
        self.hints = hints if hints is not None else QGuiApplication.styleHints()
        mode = settings.value("appearance/mode", "system")
        self._mode = mode if mode in ("system", "light", "dark") else "system"
        accent = settings.value("appearance/accent", "purple")
        self._accent = accent if accent in ACCENTS else "purple"
        self._animations = str(settings.value("appearance/animations", "true")).lower() == "true"
        try:
            scale = float(settings.value("appearance/scale", 1.0))
        except (TypeError, ValueError):
            scale = 1.0
        self._scale = scale if scale in (1.0, 1.15, 1.3) else 1.0
        self.hints.colorSchemeChanged.connect(self._system_changed)
        self._apply_palette()  # Before QML creates a visible surface.

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Property(bool, notify=changed)
    def dark(self):
        return self._mode == "dark" or (self._mode == "system" and
                                        self.hints.colorScheme() == Qt.ColorScheme.Dark)

    @Property(str, notify=changed)
    def accentName(self):
        return self._accent

    @Property(bool, notify=changed)
    def animations(self):
        return self._animations

    @Property(float, notify=changed)
    def scale(self):
        return self._scale

    @Property("QVariantMap", constant=True)
    def previewColors(self):
        return PALETTES

    @Property("QVariantMap", notify=changed)
    def colors(self):
        colors = PALETTES["dark" if self.dark else "light"].copy()
        colors["accent"], colors["accentHover"] = ACCENTS[self._accent]
        colors["selection"] = "#30264B" if self.dark else "#EEE8FB"
        return colors

    def _persist(self, key, value):
        self.settings.setValue("appearance/" + key, value)
        self.settings.sync()
        if self.settings.status() != QSettings.NoError:
            self.preferenceError.emit(self.tr("Could not save appearance preferences. Check directory permissions."))

    @Slot(str)
    def setMode(self, mode):
        if mode not in ("light", "dark", "system") or mode == self._mode:
            return
        self._mode = mode
        self._persist("mode", mode)
        self._apply_palette()
        self.changed.emit()

    @Slot(str)
    def setAccent(self, accent):
        if accent not in ACCENTS or accent == self._accent:
            return
        self._accent = accent
        self._persist("accent", accent)
        self._apply_palette()
        self.changed.emit()

    @Slot(bool)
    def setAnimations(self, value):
        if value != self._animations:
            self._animations = value
            self._persist("animations", value)
            self.changed.emit()

    @Slot(float)
    def setScale(self, value):
        if value in (1.0, 1.15, 1.3) and value != self._scale:
            self._scale = value
            self._persist("scale", value)
            self.changed.emit()

    @Slot()
    def _system_changed(self):
        if self._mode == "system":
            self._apply_palette()
            self.changed.emit()

    def _apply_palette(self):
        c = self.colors
        palette = QPalette()
        roles = {QPalette.Window: "background", QPalette.WindowText: "text", QPalette.Base: "surface",
                 QPalette.AlternateBase: "elevated", QPalette.Text: "text", QPalette.Button: "elevated",
                 QPalette.ButtonText: "text", QPalette.Highlight: "accent", QPalette.HighlightedText: "onAccent",
                 QPalette.ToolTipBase: "elevated", QPalette.ToolTipText: "text", QPalette.PlaceholderText: "secondary"}
        for role, token in roles.items():
            palette.setColor(role, QColor(c[token]))
        QGuiApplication.setPalette(palette)
