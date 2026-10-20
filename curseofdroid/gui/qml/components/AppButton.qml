import QtQuick
import QtQuick.Controls

Button {
    id: control
    property string kind: "secondary"
    property string iconName: ""
    font.pixelSize: 13 * theme.scale
    font.weight: Font.DemiBold
    padding: 12
    leftPadding: 16
    rightPadding: 16
    hoverEnabled: true
    activeFocusOnTab: true
    icon.source: iconName ? "../icons/" + iconName + ".svg" : ""
    icon.width: 18
    icon.height: 18
    readonly property color defaultForeground: kind === "primary" ? theme.colors.onAccent : (kind === "danger" ? theme.colors.error : theme.colors.text)
    property color foreground: defaultForeground
    icon.color: foreground
    palette.buttonText: foreground
    palette.brightText: foreground
    opacity: enabled ? 1 : 0.5
    Accessible.name: text
    background: Rectangle {
        radius: 9
        color: control.kind === "primary" ? (control.hovered ? theme.colors.accentHover : theme.colors.accent) : (control.hovered ? theme.colors.elevated : theme.colors.surface)
        border.width: control.visualFocus ? 2 : 1
        border.color: control.visualFocus ? theme.colors.accent : (control.kind === "primary" ? theme.colors.accent : theme.colors.border)
        Behavior on color { ColorAnimation { duration: theme.animations ? 100 : 0 } }
    }
    ToolTip.visible: hovered && text.length > 0 && width < implicitWidth
    ToolTip.text: text
}
