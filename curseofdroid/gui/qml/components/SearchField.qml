import QtQuick
import QtQuick.Controls

TextField {
    id: control
    padding: 12
    font.pixelSize: 13 * theme.scale
    color: theme.colors.text
    placeholderTextColor: theme.colors.secondary
    selectionColor: theme.colors.accent
    selectedTextColor: theme.colors.onAccent
    selectByMouse: true
    activeFocusOnTab: true
    Accessible.name: placeholderText
    background: Rectangle {
        radius: 9
        color: theme.colors.surface
        border.color: control.activeFocus ? theme.colors.accent : theme.colors.border
        border.width: control.activeFocus ? 2 : 1
    }
}
