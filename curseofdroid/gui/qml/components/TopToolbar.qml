import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: bar
    property string pageTitle: ""
    signal appearanceRequested()
    signal notificationsRequested()
    color: theme.colors.background
    implicitHeight: 76
    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 30
        anchors.rightMargin: 30
        UiText { text: qsTr("Workspace") + "  /  " + bar.pageTitle; secondary: true; font.pixelSize: 12; Layout.fillWidth: true }
        StatusBadge { text: backend.connection; tone: backend.state === "connected" ? "success" : "neutral" }
        AppButton { iconName: "activity"; onClicked: bar.notificationsRequested(); Accessible.name: qsTr("Notifications"); ToolTip.visible: hovered; ToolTip.text: qsTr("Notifications") }
        AppButton { text: qsTr("Appearance"); iconName: theme.dark ? "moon" : "sun"; onClicked: bar.appearanceRequested() }
    }
    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: theme.colors.border }
}
