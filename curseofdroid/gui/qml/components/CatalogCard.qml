import QtQuick
import QtQuick.Layouts

InfoCard {
    id: card
    required property var build
    signal inspectRequested(int identifier)
    padding: 18
    contentItem: ColumnLayout {
        spacing: 13
        RowLayout {
            Layout.fillWidth: true
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4
                UiText { text: card.build.project; font.pixelSize: 18 * theme.scale; font.weight: Font.DemiBold; Layout.fillWidth: true }
                UiText { text: (card.build.version || qsTr("Version unknown")) + "  ·  " + card.build.codename; secondary: true; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
            }
            AppButton { objectName: "build-details-" + card.build.id; text: qsTr("Details"); onClicked: card.inspectRequested(card.build.id); Accessible.name: qsTr("Details for ") + card.build.project }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            StatusBadge { text: card.build.date || qsTr("Date unknown") }
            StatusBadge { text: card.build.android ? "Android " + card.build.android : qsTr("Android unknown") }
        }
        UiText { text: card.build.filename; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true; maximumLineCount: 2; elide: Text.ElideMiddle }
        UiText {
            text: (card.build.hashKinds ? qsTr("Publisher checksum: ") + card.build.hashKinds : qsTr("No checksum in this result")) + qsTr(" · File not verified")
            secondary: true; font.pixelSize: 11 * theme.scale; Layout.fillWidth: true
        }
        UiText { visible: card.build.ended || card.build.notes.length > 0; text: card.build.notes; color: card.build.ended ? theme.colors.warning : theme.colors.secondary; font.pixelSize: 12 * theme.scale; Layout.fillWidth: true }
    }
}
