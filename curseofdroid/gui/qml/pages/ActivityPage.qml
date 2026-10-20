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
        PageHeader { title: qsTr("Activity & logs"); subtitle: qsTr("Actual operations from this session. No device serials are included in these activity entries."); Layout.fillWidth: true }
        InfoCard {
            Layout.fillWidth: true
            contentItem: ActivityList { limit: 100 }
        }
    }
}
