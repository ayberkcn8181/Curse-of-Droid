import QtQuick
import QtQuick.Controls

ComboBox {
    id: control
    implicitWidth: 150
    implicitHeight: 44
    font.pixelSize: 13 * theme.scale
    padding: 12
    activeFocusOnTab: true
    palette.text: theme.colors.text
    palette.buttonText: theme.colors.text
    palette.base: theme.colors.surface
    palette.highlight: theme.colors.accent
    palette.highlightedText: theme.colors.onAccent
    contentItem: Text {
        text: control.displayText
        font: control.font
        color: theme.colors.text
        elide: Text.ElideRight
        verticalAlignment: Text.AlignVCenter
        rightPadding: 18
    }
    indicator: Text {
        x: control.width - width - 12
        anchors.verticalCenter: parent.verticalCenter
        text: "⌄"
        font.pixelSize: 18
        color: theme.colors.secondary
    }
    background: Rectangle {
        radius: 8
        color: theme.colors.surface
        border.color: control.visualFocus ? theme.colors.accent : theme.colors.border
        border.width: control.visualFocus ? 2 : 1
    }
    delegate: ItemDelegate {
        required property var modelData
        required property int index
        width: control.width - 10
        text: control.textRole ? modelData[control.textRole] : modelData
        highlighted: control.highlightedIndex === index
        contentItem: UiText { text: parent.text; color: parent.highlighted ? theme.colors.onAccent : theme.colors.text }
        background: Rectangle { color: parent.highlighted ? theme.colors.accent : theme.colors.surface; radius: 5 }
    }
    popup: Popup {
        y: control.height + 4
        width: control.width
        padding: 5
        implicitHeight: Math.min(contentItem.implicitHeight + 10, 320)
        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
        background: Rectangle { radius: 9; color: theme.colors.surface; border.color: theme.colors.border }
    }
}
