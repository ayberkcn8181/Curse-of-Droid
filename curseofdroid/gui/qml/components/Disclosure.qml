import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var messages: []
    property bool expanded: false
    spacing: 8
    AppButton { objectName: "toggle-" + root.objectName; text: root.messages.length + qsTr(" provider error(s)") + (root.expanded ? "  ▴" : "  ▾"); onClicked: root.expanded = !root.expanded; kind: "danger" }
    ScrollView {
        id: scroll
        visible: root.expanded
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(130, errors.implicitHeight)
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            id: errors
            width: scroll.availableWidth
            Repeater { model: root.messages; UiText { required property string modelData; text: modelData; color: theme.colors.error; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true } }
        }
    }
}
