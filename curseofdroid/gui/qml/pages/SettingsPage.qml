import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

ScrollView {
    id: view
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: view.availableWidth
        spacing: 24
        PageHeader { title: qsTr("Make it yours."); subtitle: qsTr("A familiar workspace, in the light that feels right."); Layout.fillWidth: true }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 20
                UiText { text: qsTr("Appearance"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold }
                UiText { text: qsTr("Choose a theme. Changes apply immediately and are saved for your next session."); secondary: true; Layout.fillWidth: true }
                ThemeSelector { Layout.fillWidth: true }
                UiText { text: qsTr("System follows the operating system when Qt reports a preference; otherwise it uses light."); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                Rectangle { Layout.fillWidth: true; height: 1; color: theme.colors.border }
                UiText { text: qsTr("Accent color"); font.weight: Font.DemiBold }
                RowLayout {
                    spacing: 10
                    Repeater {
                        model: [{key:"purple", name:qsTr("Purple")}, {key:"blue", name:qsTr("Blue")}, {key:"teal", name:qsTr("Teal")}]
                        AppButton {
                            required property var modelData
                            text: modelData.name + (theme.accentName === modelData.key ? "  ✓" : "")
                            kind: theme.accentName === modelData.key ? "primary" : "secondary"
                            onClicked: theme.setAccent(modelData.key)
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        UiText { text: qsTr("Interface size"); font.weight: Font.DemiBold }
                        UiText { text: qsTr("Text and controls scale with your preference."); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                    }
                    AppComboBox {
                        objectName: "scaleSelector"
                        model: ["100%", "115%", "130%"]
                        currentIndex: theme.scale === 1.3 ? 2 : (theme.scale === 1.15 ? 1 : 0)
                        onActivated: theme.setScale([1.0,1.15,1.3][currentIndex])
                        Accessible.name: qsTr("Interface size")
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        UiText { text: qsTr("Motion"); font.weight: Font.DemiBold }
                        UiText { text: qsTr("Turn off transitions for a calmer workspace."); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                    }
                    Toggle {
                        checked: theme.animations
                        onToggled: theme.setAnimations(checked)
                        Accessible.name: qsTr("Enable animations")
                    }
                }
            }
        }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 12
                UiText { text: qsTr("About Curse of Droid"); font.weight: Font.DemiBold; font.pixelSize: 18 * theme.scale }
                UiText { text: qsTr("Version ") + appVersion + "  ·  GPL-3.0-or-later"; secondary: true }
                UiText { text: qsTr("The new QML workspace shares the CLI’s real Python backend. Catalog and installation workflows remain available in the existing interface while migration continues."); secondary: true; Layout.fillWidth: true }
                AppButton { text: qsTr("Open existing workflows"); iconName: "terminal"; enabled: !backend.busy; onClicked: backend.openLegacy(0) }
            }
        }
    }
}
