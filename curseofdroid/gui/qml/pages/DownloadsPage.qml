import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

ColumnLayout {
    spacing: 18
    PageHeader {
        Layout.fillWidth: true
        title: qsTr("Every byte accounted for.")
        subtitle: qsTr("Downloads from your catalog selections, with explicit integrity checks and a history that survives restart.")
    }
    InfoCard {
        Layout.fillWidth: true
        padding: 18
        contentItem: RowLayout {
            spacing: 24
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                UiText { text: qsTr("Files: %1").arg(downloadManager.rows.length) + "  ·  " + qsTr("Complete: %1").arg(downloadManager.completedCount); font.pixelSize: 18 * theme.scale; font.weight: Font.DemiBold }
                UiText { text: downloadManager.busy ? qsTr("One transfer at a time. Pause waits for the current network read.") : qsTr("Ready for your next file. Restored tasks wait for you to resume."); secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
            }
            AppButton { objectName: "pauseAllDownloads"; text: qsTr("Pause all"); enabled: downloadManager.busy; onClicked: downloadManager.pauseAll() }
        }
    }
    UiText { visible: !!downloadManager.storageError; text: downloadManager.storageError; color: theme.colors.error; Layout.fillWidth: true }
    ListView {
        id: files
        objectName: "downloadList"
        Layout.fillWidth: true
        Layout.fillHeight: true
        clip: true
        spacing: 14
        model: downloadManager.rows
        reuseItems: true
        delegate: DownloadCard { required property var modelData; width: files.width; record: modelData }
        ScrollBar.vertical: ScrollBar {}
        ColumnLayout {
            anchors.centerIn: parent
            width: parent.width - 48
            visible: downloadManager.rows.length === 0
            spacing: 12
            UiText { text: qsTr("Your next file starts in the library."); font.pixelSize: 22 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
            UiText { text: qsTr("Open a ROM or recovery build, inspect its details and choose Download file. Only publisher metadata is used for the available checks."); secondary: true; Layout.fillWidth: true }
        }
    }
    UiText { text: qsTr("Checksum matching does not certify authenticity or installation compatibility. Removing history keeps downloaded files. Nothing is installed from this page."); secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true }
}
