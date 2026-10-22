import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import "../components"

ScrollView {
    id: view
    objectName: "installationPage"
    clip: true
    contentWidth: availableWidth
    property string fileRole: "main"
    property int reviewTab: 0
    function browse(role) {
        fileRole = role
        picker.nameFilters = role === "recovery" || installPreview.kind === "gsi" ? [qsTr("Image files (*.img)")] : [qsTr("ZIP packages (*.zip)")]
        picker.open()
    }
    FileDialog {
        id: picker
        title: qsTr("Choose a local installation file")
        fileMode: FileDialog.OpenFile
        onAccepted: installPreview.setFile(view.fileRole, selectedFile)
    }
    ColumnLayout {
        width: view.availableWidth
        spacing: 18
        PageHeader {
            Layout.fillWidth: true
            title: qsTr("A plan you can inspect.")
            subtitle: qsTr("Choose local files, check their SHA-256 references and review the proposed steps. This preview does not run device operations.")
        }
        InfoCard {
            Layout.fillWidth: true
            padding: 18
            contentItem: ColumnLayout {
                spacing: 12
                RowLayout {
                    Layout.fillWidth: true
                    UiText { text: qsTr("DEVICE SNAPSHOT"); secondary: true; font.pixelSize: 10 * theme.scale; font.letterSpacing: 1; Layout.fillWidth: true }
                    StatusBadge { text: qsTr("Read-only preview"); tone: "accent" }
                }
                UiText { text: installPreview.hasDevice ? installPreview.target.name + " · " + installPreview.target.codename + " · " + installPreview.target.serial : qsTr("Select an identified device to build a plan."); font.pixelSize: 18 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true
                    AppComboBox {
                        objectName: "installDeviceSelector"
                        Layout.fillWidth: true
                        model: backend.devices
                        textRole: "label"
                        currentIndex: backend.selectedIndex
                        displayText: currentIndex < 0 ? qsTr("Select a device") : currentText
                        enabled: !backend.busy
                        onActivated: backend.selectDevice(currentIndex)
                        Accessible.name: qsTr("Installation target snapshot")
                    }
                    AppButton { text: qsTr("Refresh"); iconName: "refresh"; enabled: !backend.busy; onClicked: backend.refresh() }
                }
                UiText { text: qsTr("Discovery properties are a snapshot. Live identity, unlock, slot and capacity checks have not been run by this preview."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
            }
        }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 15
                UiText { text: qsTr("1. Choose the files"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                RowLayout {
                    AppButton { objectName: "installRomType"; text: qsTr("ROM package"); kind: installPreview.kind === "rom" ? "primary" : "secondary"; onClicked: installPreview.setKind("rom") }
                    AppButton { objectName: "installGsiType"; text: qsTr("GSI system image"); kind: installPreview.kind === "gsi" ? "primary" : "secondary"; onClicked: installPreview.setKind("gsi") }
                    Item { Layout.fillWidth: true }
                }
                FileInput { objectName: "installMainFile"; Layout.fillWidth: true; label: installPreview.kind === "rom" ? qsTr("ROM ZIP") : qsTr("Unpacked system image (.img)"); path: installPreview.paths.main; onBrowseRequested: view.browse("main"); onClearRequested: installPreview.setPath("main", "") }
                FileInput { Layout.fillWidth: true; visible: installPreview.kind === "rom"; label: qsTr("Recovery image (optional, temporary boot)"); path: installPreview.paths.recovery; onBrowseRequested: view.browse("recovery"); onClearRequested: installPreview.setPath("recovery", "") }
                FileInput { Layout.fillWidth: true; visible: installPreview.kind === "rom"; label: qsTr("Add-on ZIP (optional)"); path: installPreview.paths.addon; onBrowseRequested: view.browse("addon"); onClearRequested: installPreview.setPath("addon", "") }
                UiText { text: qsTr("Each file needs its own adjacent .manifest.json reference with SHA-256, size, source and explicit device targets. A matching hash checks bytes; it does not authenticate the publisher."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
                RowLayout {
                    Layout.fillWidth: true
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        UiText { text: qsTr("Include data erase in the plan"); font.weight: Font.DemiBold; Layout.fillWidth: true }
                        UiText { text: installPreview.wipeData ? qsTr("Data erase deletes apps, accounts and internal storage. No erase runs in this preview.") : qsTr("Retain data only when the device and ROM instructions explicitly permit it."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
                    }
                    Toggle { objectName: "installWipeToggle"; checked: installPreview.wipeData; onClicked: installPreview.setWipeData(checked); Accessible.name: qsTr("Include data erase in the plan") }
                }
            }
        }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ColumnLayout {
                spacing: 14
                UiText { text: qsTr("2. Check the references"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                UiText { objectName: "installStatus"; text: installPreview.message; color: installPreview.state === "error" ? theme.colors.error : theme.colors.text; Layout.fillWidth: true }
                AppProgressBar { objectName: "installProgress"; Layout.fillWidth: true; visible: installPreview.busy || installPreview.state === "complete"; from: 0; to: 1; value: installPreview.fraction; complete: installPreview.state === "complete"; indeterminate: installPreview.busy && installPreview.fraction === 0 }
                UiText { text: installPreview.progressLabel; secondary: true; visible: installPreview.busy || installPreview.state === "complete"; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
                RowLayout {
                    AppButton { objectName: "verifyInstallPlan"; text: installPreview.state === "complete" ? qsTr("Verify again") : qsTr("Verify & prepare plan"); kind: "primary"; enabled: installPreview.canVerify; onClicked: installPreview.verify() }
                    AppButton { objectName: "cancelInstallVerification"; text: qsTr("Cancel verification"); visible: installPreview.busy; enabled: installPreview.state !== "cancelling"; onClicked: installPreview.cancel() }
                    Item { Layout.fillWidth: true }
                }
            }
        }
        InfoCard {
            Layout.fillWidth: true
            visible: installPreview.state === "complete"
            contentItem: ColumnLayout {
                spacing: 16
                UiText { text: qsTr("3. Review before proceeding"); font.pixelSize: 19 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Repeater {
                    model: installPreview.blockers
                    UiText { required property string modelData; text: modelData; color: theme.colors.warning; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                }
                UiText { text: qsTr("Installation is unavailable from this preview. Publisher authenticity, image compatibility, device-specific instructions and live execution checks remain required."); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                Flow {
                    Layout.fillWidth: true
                    spacing: 8
                    AppButton { text: qsTr("Steps"); kind: view.reviewTab === 0 ? "primary" : "secondary"; onClicked: view.reviewTab = 0 }
                    AppButton { text: qsTr("Files & references"); kind: view.reviewTab === 1 ? "primary" : "secondary"; onClicked: view.reviewTab = 1 }
                    AppButton { text: qsTr("Command plan"); kind: view.reviewTab === 2 ? "primary" : "secondary"; onClicked: view.reviewTab = 2 }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: view.reviewTab === 0
                    spacing: 16
                    Repeater {
                        model: installPreview.steps
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 5
                            UiText { text: modelData.number + ". " + modelData.title; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            UiText { text: modelData.risk === "data-loss" ? qsTr("DATA LOSS") : (modelData.risk === "system-write" ? qsTr("WRITES SYSTEM") : ""); visible: !!text; color: theme.colors.warning; font.pixelSize: 10 * theme.scale; font.weight: Font.Bold; Layout.fillWidth: true }
                            UiText { text: modelData.explain; secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                            UiText { text: qsTr("On the phone: ") + modelData.manual; visible: !!modelData.manual; secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                        }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    visible: view.reviewTab === 1
                    spacing: 18
                    Repeater {
                        model: installPreview.files
                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 7
                            UiText { text: modelData.name + " · " + modelData.kind; font.weight: Font.DemiBold; Layout.fillWidth: true }
                            UiText { text: qsTr("SHA-256 reference matched · ") + modelData.size + qsTr(" bytes"); color: theme.colors.success; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                            UiText { text: modelData.sha256; font.family: "monospace"; font.pixelSize: 11 * theme.scale; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                            UiText { text: qsTr("Declared devices: ") + modelData.devices; secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
                            UiText { text: qsTr("Reference source (not authenticated): ") + modelData.source; secondary: true; font.pixelSize: 11 * theme.scale; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
                        }
                    }
                }
                TextArea {
                    objectName: "installCommandPlan"
                    Layout.fillWidth: true
                    visible: view.reviewTab === 2
                    text: installPreview.planText
                    readOnly: true
                    selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    font.family: "monospace"
                    font.pixelSize: 11 * theme.scale
                    color: theme.colors.text
                    textFormat: TextEdit.PlainText
                    padding: 14
                    background: Rectangle { radius: 9; color: theme.colors.background; border.color: theme.colors.border }
                    Accessible.name: qsTr("Read-only command plan")
                }
            }
        }
        Item { Layout.preferredHeight: 12 }
    }
}
