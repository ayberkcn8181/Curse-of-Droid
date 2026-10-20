import QtQuick
import QtQuick.Layouts

RowLayout {
    property string label: ""
    property string value: ""
    spacing: 12
    UiText { text: label; secondary: true; Layout.preferredWidth: 135 * theme.scale; font.pixelSize: 12 * theme.scale }
    UiText { text: value || qsTr("Unknown"); Layout.fillWidth: true; font.pixelSize: 12 * theme.scale; font.weight: Font.Medium }
}
