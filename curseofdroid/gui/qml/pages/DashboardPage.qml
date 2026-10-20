import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

ScrollView {
    id: view
    signal detailsRequested()
    signal activityRequested()
    signal catalogRequested()
    signal recoveryRequested()
    clip: true
    contentWidth: availableWidth
    ColumnLayout {
        width: view.availableWidth
        spacing: 22
        PageHeader {
            Layout.fillWidth: true
            title: qsTr("A little freedom. A lot of possibility.")
            subtitle: qsTr("Your Android workspace — discover, understand and make an informed next move.")
        }
        RowLayout {
            visible: backend.devices.length > 1
            Layout.fillWidth: true
            UiText { text: qsTr("Selected device") }
            AppComboBox {
                Layout.fillWidth: true
                model: backend.devices
                textRole: "label"
                currentIndex: backend.selectedIndex
                displayText: currentIndex < 0 ? qsTr("Select a device explicitly") : currentText
                onActivated: backend.selectDevice(currentIndex)
                Accessible.name: qsTr("Selected device")
            }
        }
        InfoCard {
            visible: backend.error.length > 0
            Layout.fillWidth: true
            padding: 16
            contentItem: UiText { text: backend.error; color: theme.colors.error }
        }
        ProgressBar { visible: backend.busy; indeterminate: true; Layout.fillWidth: true; Accessible.name: qsTr("Device operation in progress") }
        DeviceCard { Layout.fillWidth: true; onDetailsRequested: view.detailsRequested() }
        GridLayout {
            Layout.fillWidth: true
            columns: view.availableWidth < 850 ? 2 : 3
            columnSpacing: 16
            rowSpacing: 16
            StatCard { Layout.fillWidth: true; title: qsTr("USB CONNECTIONS"); value: backend.scanned ? backend.devices.length.toString() : "—"; detail: backend.scanned ? qsTr("From the latest read-only discovery") : qsTr("Awaiting read-only discovery") }
            StatCard { Layout.fillWidth: true; title: qsTr("PLATFORM-TOOLS"); value: backend.toolsReady ? qsTr("Ready") : qsTr("Not installed"); detail: backend.toolsReady ? qsTr("Source: ") + backend.toolsSource : qsTr("Google adb & fastboot required") }
            StatCard { Layout.fillWidth: true; Layout.columnSpan: view.availableWidth < 850 ? 2 : 1; title: qsTr("ROM PROJECTS"); value: backend.romProjects.toString(); detail: qsTr("Catalog providers, not compatible builds") }
        }
        GridLayout {
            Layout.fillWidth: true
            columns: view.availableWidth < 720 ? 1 : 2
            columnSpacing: 18
            rowSpacing: 18
            InfoCard {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                contentItem: ColumnLayout {
                    spacing: 16
                    UiText { text: qsTr("Take the next step"); font.weight: Font.DemiBold; font.pixelSize: 17 * theme.scale }
                    UiText { text: qsTr("Explore ROM and recovery publishers in the QML catalog."); secondary: true; Layout.fillWidth: true }
                    AppButton { text: qsTr("Explore ROM library"); iconName: "layers"; Layout.fillWidth: true; enabled: !backend.busy; onClicked: view.catalogRequested() }
                    AppButton { text: qsTr("Find recovery"); iconName: "shield"; Layout.fillWidth: true; onClicked: view.recoveryRequested() }
                    AppButton { text: qsTr("Open existing installer"); iconName: "wand"; Layout.fillWidth: true; enabled: !backend.busy; onClicked: backend.openLegacy(3) }
                    UiText { text: qsTr("Installation remains an early-development workflow. Review the device-specific instructions and every command."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
                }
            }
            InfoCard {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignTop
                contentItem: ColumnLayout {
                    spacing: 16
                    RowLayout {
                        Layout.fillWidth: true
                        UiText { text: qsTr("Recent activity"); font.weight: Font.DemiBold; font.pixelSize: 17 * theme.scale; Layout.fillWidth: true }
                        AppButton { text: qsTr("View all"); onClicked: view.activityRequested() }
                    }
                    ActivityList { Layout.fillWidth: true; limit: 4 }
                }
            }
        }
        UiText { text: qsTr("Made for informed choices. Device information is shown only when reported by the backend."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true; Layout.bottomMargin: 8 }
    }
}
