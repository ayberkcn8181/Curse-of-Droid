import QtQuick
import QtQuick.Controls

ProgressBar {
    id: control
    property bool complete: false
    property real travel: 0.5
    padding: 0
    implicitHeight: 6
    background: Rectangle { implicitHeight: 6; radius: 3; color: theme.colors.elevated }
    contentItem: Item {
        implicitHeight: 6
        Rectangle {
            id: indicator
            width: parent.width * (control.indeterminate ? 0.25 : control.visualPosition)
            height: parent.height
            x: control.indeterminate ? (parent.width - width) * control.travel : 0
            radius: 3
            color: control.complete ? theme.colors.success : theme.colors.accent
        }
    }
    NumberAnimation on travel { from: 0; to: 1; duration: 1100; loops: Animation.Infinite; running: control.visible && control.indeterminate && theme.animations }
}
