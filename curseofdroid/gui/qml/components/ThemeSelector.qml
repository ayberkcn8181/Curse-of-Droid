import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

RowLayout {
    id: selector
    spacing: 14
    Repeater {
        model: [ {mode: "light", label: qsTr("Light"), detail: qsTr("A brighter workspace")},
                 {mode: "dark", label: qsTr("Dark"), detail: qsTr("Focus after hours")},
                 {mode: "system", label: qsTr("System"), detail: qsTr("Follow your desktop")} ]
        delegate: AbstractButton {
            id: option
            required property var modelData
            objectName: "theme-" + modelData.mode
            Layout.fillWidth: true
            implicitHeight: 168 * theme.scale
            checkable: true
            checked: theme.mode === modelData.mode
            activeFocusOnTab: true
            Accessible.name: modelData.label
            Accessible.role: Accessible.RadioButton
            Accessible.checked: checked
            onClicked: theme.setMode(modelData.mode)
            background: Rectangle {
                radius: 12
                color: theme.colors.surface
                border.width: option.checked || option.visualFocus ? 2 : 1
                border.color: option.checked || option.visualFocus ? theme.colors.accent : theme.colors.border
            }
            contentItem: ColumnLayout {
                spacing: 8
                anchors.margins: 14
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 74 * theme.scale
                    radius: 6
                    color: option.modelData.mode === "light" ? theme.previewColors.light.background : theme.previewColors.dark.background
                    border.color: theme.colors.border
                    Rectangle {
                        width: parent.width * 0.24; height: parent.height - 2
                        x: 1; y: 1; radius: 5
                        color: option.modelData.mode === "light" ? theme.previewColors.light.elevated : theme.previewColors.dark.elevated
                    }
                    Rectangle {
                        x: parent.width * 0.31; y: 14; width: parent.width * 0.58; height: 7; radius: 3
                        color: theme.colors.accent
                    }
                    Rectangle {
                        x: parent.width * 0.31; y: 32; width: parent.width * 0.58; height: 25; radius: 4
                        color: option.modelData.mode === "light" ? theme.previewColors.light.elevated : theme.previewColors.dark.elevated
                    }
                    Rectangle {
                        visible: option.modelData.mode === "system"
                        anchors.right: parent.right; width: parent.width * 0.35; height: parent.height; radius: 5
                        color: theme.previewColors.light.background
                    }
                }
                UiText { text: option.modelData.label + (option.checked ? "  ✓" : ""); font.weight: Font.DemiBold; Layout.fillWidth: true }
                UiText { text: option.modelData.detail; secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
            }
            leftPadding: 14; rightPadding: 14; topPadding: 14; bottomPadding: 14
        }
    }
}
