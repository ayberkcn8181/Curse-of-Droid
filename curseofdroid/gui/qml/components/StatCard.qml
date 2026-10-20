import QtQuick
import QtQuick.Layouts

InfoCard {
    property string title: ""
    property string value: ""
    property string detail: ""
    contentItem: ColumnLayout {
        spacing: 10
        UiText { text: title; secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
        UiText { text: value; font.pixelSize: 24 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
        UiText { text: detail; secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
    }
}
