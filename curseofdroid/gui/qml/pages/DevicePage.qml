import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

ScrollView {
    id: view
    clip: true
    contentWidth: availableWidth
    readonly property var d: backend.device
    function state(key) { return d[key] === "yes" ? qsTr("Yes") : (d[key] === "no" ? qsTr("No") : qsTr("Unknown")) }
    ColumnLayout {
        width: view.availableWidth
        spacing: 22
        PageHeader { title: qsTr("My device"); subtitle: qsTr("Reported properties from the selected device. Unknown is never treated as false."); Layout.fillWidth: true }
        RowLayout {
            Layout.fillWidth: true
            AppComboBox {
                Layout.fillWidth: true
                model: backend.devices; textRole: "label"; currentIndex: backend.selectedIndex
                displayText: currentIndex < 0 ? qsTr("Select a device") : currentText
                onActivated: backend.selectDevice(currentIndex)
                Accessible.name: qsTr("Selected device")
            }
            AppButton { text: qsTr("Refresh"); iconName: "refresh"; enabled: !backend.busy; onClicked: backend.refresh() }
        }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 16
                UiText { text: backend.error || (Object.keys(view.d).length ? qsTr("Identity & system") : qsTr("No identified device")); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                FieldRow { label: qsTr("Manufacturer"); value: view.d.manufacturer || view.d.brand || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Model"); value: view.d.market_name || view.d.model || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Codename"); value: view.d.codename || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Android"); value: view.d.android_version || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Build fingerprint"); value: view.d.fingerprint || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Security patch"); value: view.d.security_patch || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("CPU architecture"); value: view.d.abi || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("SoC"); value: view.d.soc || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Storage"); value: qsTr("Not reported by current backend"); Layout.fillWidth: true }
            }
        }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 15
                UiText { text: qsTr("Security & compatibility"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold }
                FieldRow { label: qsTr("Bootloader unlocked"); value: view.state("bootloader_unlocked"); Layout.fillWidth: true }
                FieldRow { label: qsTr("A/B slots"); value: view.state("ab"); Layout.fillWidth: true }
                FieldRow { label: qsTr("Active slot"); value: view.d.current_slot || ""; Layout.fillWidth: true }
                FieldRow { label: qsTr("Dynamic partitions"); value: view.state("dynamic_partitions"); Layout.fillWidth: true }
                FieldRow { label: qsTr("Treble"); value: view.state("treble"); Layout.fillWidth: true }
                FieldRow { label: qsTr("Verified Boot"); value: view.d.verified_boot_state || ""; Layout.fillWidth: true }
                UiText { text: qsTr("Properties do not certify installation compatibility. Verify the exact variant, firmware, partition layout and publisher instructions."); secondary: true; Layout.fillWidth: true }
            }
        }
    }
}
