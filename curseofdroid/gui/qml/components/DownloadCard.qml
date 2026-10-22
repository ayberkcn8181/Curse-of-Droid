import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

InfoCard {
    id: card
    required property var record
    padding: 18
    function bytes(value) { return (Number(value) / 1048576).toFixed(1) + " MiB" }
    function stateName(state) {
        return {"queued":qsTr("Queued"), "downloading":qsTr("Downloading"), "checksums":qsTr("Fetching checksum"),
            "verifying":qsTr("Checking file"), "complete":qsTr("Complete"), "paused":qsTr("Paused"),
            "pausing":qsTr("Pausing…"), "failed":qsTr("Failed"), "needs-check":qsTr("Recheck needed"), "missing":qsTr("File missing")}[state] || state
    }
    contentItem: ColumnLayout {
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            UiText { text: card.record.project + "  ·  " + card.record.codename; font.pixelSize: 16 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
            StatusBadge { text: card.stateName(card.record.state); tone: card.record.state === "complete" ? "success" : (["failed", "needs-check", "missing"].indexOf(card.record.state) >= 0 ? "warning" : "neutral") }
        }
        UiText { text: card.record.filename; secondary: true; font.pixelSize: 12 * theme.scale; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true }
        AppProgressBar {
            Layout.fillWidth: true
            from: 0; to: 1; value: card.record.fraction
            indeterminate: card.record.active && (!card.record.total || ["checksums", "verifying"].indexOf(card.record.state) >= 0)
            complete: card.record.state === "complete"
            Accessible.name: qsTr("File progress")
        }
        RowLayout {
            Layout.fillWidth: true
            UiText { text: card.bytes(card.record.done) + (card.record.total ? " / " + card.bytes(card.record.total) : qsTr(" · total unknown")); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
            UiText { text: card.record.hashes ? card.record.hashes.toUpperCase() : qsTr("No publisher checksum"); color: card.record.hashes ? theme.colors.secondary : theme.colors.warning; font.pixelSize: 11 * theme.scale }
        }
        UiText { text: card.record.integrity; color: card.record.state === "complete" && card.record.hashes.indexOf("sha256") >= 0 ? theme.colors.success : theme.colors.secondary; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
        UiText { visible: !!card.record.error; text: card.record.error; color: theme.colors.warning; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
        Flow {
            Layout.fillWidth: true
            spacing: 8
            AppButton { objectName: "pause-" + card.record.id; visible: card.record.active || card.record.state === "queued"; text: qsTr("Pause"); enabled: card.record.state !== "pausing"; onClicked: downloadManager.pause(card.record.id) }
            AppButton { objectName: "resume-" + card.record.id; visible: ["paused", "failed", "missing"].indexOf(card.record.state) >= 0; text: card.record.state === "paused" ? qsTr("Resume") : qsTr("Retry download"); kind: "primary"; onClicked: downloadManager.resume(card.record.id) }
            AppButton { objectName: "recheck-" + card.record.id; visible: ["complete", "needs-check"].indexOf(card.record.state) >= 0; text: card.record.canCheck ? qsTr("Recheck file") : qsTr("Check availability"); onClicked: downloadManager.recheck(card.record.id) }
            AppButton { visible: ["complete", "needs-check"].indexOf(card.record.state) >= 0; text: qsTr("Open folder"); onClicked: downloadManager.openFolder(card.record.id) }
            AppButton { visible: !card.record.active; text: qsTr("Remove from history"); onClicked: downloadManager.remove(card.record.id) }
        }
    }
}
