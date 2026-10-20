import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

InfoCard {
    id: card
    property var device: backend.device
    signal detailsRequested()
    readonly property bool identified: Object.keys(device).length > 0
    contentItem: RowLayout {
        spacing: 26
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 17
            StatusBadge { text: card.identified ? qsTr("DEVICE OVERVIEW") : qsTr("LET’S GET CONNECTED"); tone: card.identified ? "success" : "neutral" }
            EmptyState {
                Layout.fillWidth: true
                title: card.identified ? (card.device.market_name || card.device.model || card.device.codename || qsTr("Connected device")) : (backend.state === "selection" ? qsTr("Choose your device") : qsTr("Your next chapter starts here."))
                detail: card.identified ? ((card.device.brand || qsTr("Unknown manufacturer")) + "  ·  " + (card.device.codename || qsTr("Unknown codename"))) : qsTr("Connect an Android device to see its identity, bootloader state and compatibility. Discovery only reads device information.")
            }
            RowLayout {
                visible: card.identified
                Layout.fillWidth: true
                spacing: 22
                ColumnLayout {
                    UiText { text: qsTr("ANDROID"); secondary: true; font.pixelSize: 10 * theme.scale }
                    UiText { text: card.device.android_version || qsTr("Unknown"); font.weight: Font.DemiBold }
                }
                ColumnLayout {
                    UiText { text: qsTr("BATTERY"); secondary: true; font.pixelSize: 10 * theme.scale }
                    UiText { text: card.device.battery_percent === undefined || card.device.battery_percent === null ? qsTr("Unknown") : card.device.battery_percent + "%"; font.weight: Font.DemiBold }
                }
                ColumnLayout {
                    UiText { text: qsTr("MODE"); secondary: true; font.pixelSize: 10 * theme.scale }
                    UiText { text: card.device.mode || qsTr("Unknown"); font.weight: Font.DemiBold }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                AppButton {
                    text: backend.busy ? qsTr("Working…") : (backend.toolsReady ? qsTr("Refresh devices") : qsTr("Install platform-tools"))
                    kind: "primary"
                    iconName: backend.toolsReady ? "refresh" : "download"
                    enabled: !backend.busy
                    onClicked: backend.toolsReady ? backend.refresh() : backend.installTools()
                }
                AppButton { text: qsTr("View details"); visible: card.identified; onClicked: card.detailsRequested() }
            }
        }
        Rectangle {
            visible: card.width > 600
            Layout.preferredWidth: 145
            Layout.preferredHeight: 196
            radius: 26
            color: theme.colors.elevated
            Image { anchors.centerIn: parent; source: "../icons/device-illustration.svg"; width: 100; height: 160; sourceSize: Qt.size(200,320) }
        }
    }
}
