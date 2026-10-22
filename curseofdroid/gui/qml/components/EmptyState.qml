import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property string title: ""
    property string detail: ""
    spacing: 12
    UiText { text: title; font.pixelSize: 21 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
    UiText { text: detail; secondary: true; Layout.fillWidth: true }
}
