import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string label: ""
    property string path: ""
    signal browseRequested()
    signal clearRequested()
    spacing: 7
    UiText { text: root.label; font.pixelSize: 12 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
    RowLayout {
        Layout.fillWidth: true
        spacing: 10
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.max(44, fileText.implicitHeight + 20)
            radius: 9
            color: theme.colors.background
            border.color: theme.colors.border
            UiText {
                id: fileText
                anchors.fill: parent
                anchors.margins: 10
                text: root.path || qsTr("No file selected")
                secondary: !root.path
                font.pixelSize: 12 * theme.scale
                wrapMode: Text.WrapAnywhere
            }
        }
        AppButton { text: qsTr("Browse"); onClicked: root.browseRequested(); Accessible.name: qsTr("Browse: ") + root.label }
        AppButton { text: qsTr("Clear"); visible: !!root.path; onClicked: root.clearRequested(); Accessible.name: qsTr("Clear: ") + root.label }
    }
}
