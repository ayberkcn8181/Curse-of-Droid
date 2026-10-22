import QtQuick
import QtQuick.Controls

Popup {
    id: toast
    property string message: ""
    function show(text) { message = text; open(); dismiss.restart() }
    width: 480
    padding: 18
    contentItem: UiText { text: toast.message }
    background: Rectangle { color: theme.colors.elevated; radius: 12; border.color: theme.colors.border }
    Timer { id: dismiss; interval: 6000; onTriggered: toast.close() }
}
