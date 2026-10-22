import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property string title: ""
    property string subtitle: ""
    spacing: 8
    UiText { text: title; font.pixelSize: 29 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
    UiText { text: subtitle; secondary: true; Layout.fillWidth: true }
}
