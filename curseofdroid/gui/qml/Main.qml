import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import "components"
import "pages"

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    width: Math.max(minimumWidth, Math.min(1260, Screen.desktopAvailableWidth))
    height: Math.max(minimumHeight, Math.min(900, Screen.desktopAvailableHeight))
    minimumWidth: 920
    minimumHeight: 680
    visible: true
    title: "Curse of Droid"
    color: theme.colors.background
    font.family: Qt.platform.os === "windows" ? "Segoe UI" : "Noto Sans"
    palette.window: theme.colors.background
    palette.windowText: theme.colors.text
    palette.base: theme.colors.surface
    palette.alternateBase: theme.colors.elevated
    palette.text: theme.colors.text
    palette.button: theme.colors.elevated
    palette.buttonText: theme.colors.text
    palette.highlight: theme.colors.accent
    palette.highlightedText: theme.colors.onAccent
    palette.toolTipBase: theme.colors.elevated
    palette.toolTipText: theme.colors.text
    property string currentPage: "dashboard"
    readonly property var pageKeys: ["dashboard", "device", "activity", "settings"]
    readonly property var pageTitles: [qsTr("Dashboard"), qsTr("My device"), qsTr("Activity & logs"), qsTr("Settings")]
    onClosing: function(close) {
        if (backend.busy) {
            close.accepted = false
            toast.show(qsTr("An operation is running. Wait for it to finish before closing."))
        }
    }
    Component.onCompleted: if (autoDiscover) backend.refresh()
    Shortcut { sequence: "Ctrl+1"; onActivated: window.currentPage = "dashboard" }
    Shortcut { sequence: "Ctrl+2"; onActivated: window.currentPage = "device" }
    Shortcut { sequence: "Ctrl+,"; onActivated: window.currentPage = "settings" }
    Shortcut { sequence: "F5"; onActivated: backend.refresh() }
    RowLayout {
        anchors.fill: parent
        spacing: 0
        NavigationSidebar {
            Layout.fillHeight: true
            Layout.preferredWidth: implicitWidth
            currentPage: window.currentPage
            onNavigate: function(page) { window.currentPage = page }
        }
        Rectangle { Layout.fillHeight: true; width: 1; color: theme.colors.border }
        ColumnLayout {
            Layout.fillHeight: true
            Layout.fillWidth: true
            spacing: 0
            TopToolbar {
                Layout.fillWidth: true
                pageTitle: window.pageTitles[window.pageKeys.indexOf(window.currentPage)] || ""
                onNotificationsRequested: notifications.open()
                onAppearanceRequested: window.currentPage = "settings"
            }
            StackLayout {
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.margins: 30
                currentIndex: window.pageKeys.indexOf(window.currentPage)
                DashboardPage { onDetailsRequested: window.currentPage = "device"; onActivityRequested: window.currentPage = "activity" }
                DevicePage {}
                ActivityPage {}
                SettingsPage {}
            }
        }
    }
    NotificationToast {
        id: toast
        anchors.centerIn: Overlay.overlay
        width: Math.min(window.width - 80, 520)
    }
    NotificationCenter {
        id: notifications
        anchors.centerIn: Overlay.overlay
        width: Math.min(window.width - 80, 500)
    }
    Connections { target: backend; function onNotice(message) { toast.show(message) } }
    Connections { target: theme; function onPreferenceError(message) { toast.show(message) } }
}
