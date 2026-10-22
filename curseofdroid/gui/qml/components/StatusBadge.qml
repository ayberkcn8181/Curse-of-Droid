import QtQuick
import QtQuick.Layouts

Rectangle {
    id: badge
    property string text: ""
    property string tone: "neutral"
    readonly property color ink: tone === "success" ? theme.colors.success : (tone === "warning" ? theme.colors.warning : theme.colors.secondary)
    implicitWidth: contents.implicitWidth + 22
    implicitHeight: contents.implicitHeight + 12
    radius: height / 2
    color: theme.colors.elevated
    RowLayout {
        id: contents
        anchors.centerIn: parent
        spacing: 7
        Rectangle { width: 6; height: 6; radius: 3; color: badge.ink }
        UiText { text: badge.text; color: badge.ink; font.pixelSize: 11 * theme.scale; font.weight: Font.DemiBold }
    }
}
