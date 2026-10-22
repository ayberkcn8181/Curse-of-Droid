import QtQuick
import QtQuick.Controls

Switch {
    id: control
    implicitWidth: 52
    implicitHeight: 36
    activeFocusOnTab: true
    indicator: Rectangle {
        anchors.centerIn: parent
        width: 46; height: 26; radius: 13
        color: control.checked ? theme.colors.accent : theme.colors.elevated
        border.color: control.visualFocus ? theme.colors.accent : theme.colors.border
        border.width: control.visualFocus ? 2 : 1
        Rectangle {
            x: control.checked ? 23 : 3; y: 3; width: 20; height: 20; radius: 10
            color: control.checked ? theme.colors.onAccent : theme.colors.secondary
            Behavior on x { NumberAnimation { duration: theme.animations ? 100 : 0 } }
        }
    }
}
