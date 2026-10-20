import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: list
    property int limit: 6
    spacing: 14
    UiText { text: qsTr("No operations in this session yet."); secondary: true; visible: backend.activity.length === 0; Layout.fillWidth: true }
    Repeater {
        model: backend.activity.slice(0, list.limit)
        delegate: RowLayout {
            required property var modelData
            spacing: 12
            Layout.fillWidth: true
            Rectangle { width: 7; height: 7; radius: 3.5; color: modelData.status === "error" ? theme.colors.error : (modelData.status === "success" ? theme.colors.success : theme.colors.secondary) }
            UiText { text: modelData.message; Layout.fillWidth: true; font.pixelSize: 12 * theme.scale }
            UiText { text: modelData.time; secondary: true; font.pixelSize: 11 * theme.scale }
        }
    }
}
