import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    width: 500
    padding: 22
    contentItem: ColumnLayout {
        spacing: 20
        UiText { text: qsTr("Session notifications"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold }
        ActivityList { limit: 6; Layout.fillWidth: true }
        UiText { text: qsTr("Full session history is available in Activity & logs."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
    }
    background: Rectangle { color: theme.colors.surface; radius: 15; border.color: theme.colors.border }
}
