import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Popup {
    id: details
    required property var catalog
    property var build: catalog.selected
    modal: true
    focus: true
    padding: 22
    width: Math.min(parent.width - 60, 720)
    height: Math.min(parent.height - 60, 700)
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { radius: 15; color: theme.colors.surface; border.color: theme.colors.border }
    contentItem: ScrollView {
        id: scroll
        clip: true
        contentWidth: availableWidth
        ColumnLayout {
            width: scroll.availableWidth
            spacing: 15
            RowLayout {
                Layout.fillWidth: true
                UiText { text: details.build.project || qsTr("Build details"); font.pixelSize: 22 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                AppButton { objectName: "queueSelectedDownload"; text: qsTr("Download file"); kind: "primary"; visible: !!details.build.direct; enabled: !!details.build.sourceUrl; onClicked: { details.catalog.queueSelected(); details.close() } }
                AppButton { text: qsTr("Close"); onClicked: details.close() }
            }
            UiText { text: qsTr("Codename matches are catalog results, not verified installation compatibility."); color: theme.colors.warning; Layout.fillWidth: true }
            FieldRow { label: qsTr("Device codename"); value: details.build.codename || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Device name"); value: details.build.deviceName || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Version"); value: details.build.version || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Android"); value: details.build.android || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Release date"); value: details.build.date || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Variant"); value: details.build.variant || ""; Layout.fillWidth: true }
            FieldRow { label: qsTr("Project status"); value: details.build.ended ? qsTr("Ended (provider note)") : qsTr("Unknown"); Layout.fillWidth: true }
            FieldRow { label: qsTr("Official status"); value: qsTr("Not reported by this source"); Layout.fillWidth: true }
            UiText { text: details.build.notes || qsTr("No additional provider notes."); secondary: true; Layout.fillWidth: true }
            UiText { text: qsTr("Published files"); font.weight: Font.DemiBold }
            Repeater {
                model: details.build.artifacts || []
                UiText { required property var modelData; text: modelData.filename + (modelData.size ? "  ·  " + modelData.size + qsTr(" bytes") : ""); font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
            }
            UiText { text: qsTr("Publisher checksums"); font.weight: Font.DemiBold }
            Repeater {
                model: Object.keys(details.build.hashes || {})
                UiText { required property string modelData; text: modelData.toUpperCase() + ": " + details.build.hashes[modelData]; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere }
            }
            UiText { visible: Object.keys(details.build.hashes || {}).length === 0; text: qsTr("No checksum is loaded for this result. Check the publisher’s download page."); secondary: true; Layout.fillWidth: true }
            UiText { text: qsTr("A published checksum is metadata. No downloaded file has been verified here. Firmware, device variant and installation method must be reviewed before installation."); color: theme.colors.warning; Layout.fillWidth: true }
            UiText { text: details.build.sourceUrl || qsTr("Source URL is unavailable or not a permitted HTTPS link."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true; wrapMode: Text.WrapAnywhere }
            Flow {
                Layout.fillWidth: true
                spacing: 10
                AppButton { text: details.build.direct ? qsTr("Open publisher file") : qsTr("Open download page"); enabled: !!details.build.sourceUrl; onClicked: details.catalog.openSelectedLink("source") }
                AppButton { text: qsTr("Instructions"); enabled: !!details.build.instructionsUrl; onClicked: details.catalog.openSelectedLink("instructions") }
                AppButton { text: qsTr("Project website"); enabled: !!details.build.homepageUrl; onClicked: details.catalog.openSelectedLink("project") }
            }
        }
    }
    Connections { target: details.catalog; function onChanged() { if (Object.keys(details.catalog.selected).length === 0) details.close() } }
}
