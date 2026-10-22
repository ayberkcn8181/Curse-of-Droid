import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: sidebar
    property bool collapsed: false
    property string currentPage: "dashboard"
    signal navigate(string page)
    color: theme.colors.surface
    implicitWidth: collapsed ? 76 : 238
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 8
        RowLayout {
            Layout.topMargin: 6
            Layout.bottomMargin: sidebar.height < 780 ? 12 : 28
            spacing: 11
            Image { source: "../icons/mark.svg"; sourceSize: Qt.size(32,32); Layout.preferredWidth: 32; Layout.preferredHeight: 32 }
            ColumnLayout {
                visible: !sidebar.collapsed
                spacing: 1
                UiText { text: "CURSE OF DROID"; font.pixelSize: 12; font.weight: Font.Bold }
                UiText { text: qsTr("Your device. Your choice."); font.pixelSize: 10; secondary: true }
            }
        }
        UiText { visible: !sidebar.collapsed; text: qsTr("WORKSPACE"); secondary: true; font.pixelSize: 10; font.letterSpacing: 1.4; Layout.leftMargin: 12; Layout.bottomMargin: 8 }
        Repeater {
            model: [ {key:"dashboard", title:qsTr("Dashboard"), icon:"dashboard", ready:true},
                     {key:"device", title:qsTr("My device"), icon:"phone", ready:true},
                     {key:"roms", title:qsTr("ROM library"), icon:"layers", ready:true},
                     {key:"recovery", title:qsTr("Recovery manager"), icon:"shield", ready:true},
                     {key:"install", title:qsTr("Installation plan"), icon:"wand", ready:true},
                     {key:"downloads", title:qsTr("Downloads"), icon:"download", ready:true},
                     {key:"advanced", title:qsTr("Advanced tools"), icon:"terminal", ready:false},
                     {key:"activity", title:qsTr("Activity & logs"), icon:"activity", ready:true} ]
            delegate: AppButton {
                required property var modelData
                Layout.fillWidth: true
                font.pixelSize: 12 * theme.scale
                font.weight: Font.Medium
                topPadding: sidebar.height < 780 ? 7 : 12
                bottomPadding: sidebar.height < 780 ? 7 : 12
                leftPadding: 10
                rightPadding: 10
                text: sidebar.collapsed ? "" : modelData.title.replace(/&/g, "&&")
                iconName: modelData.icon
                display: sidebar.collapsed ? AbstractButton.IconOnly : AbstractButton.TextBesideIcon
                enabled: modelData.ready
                checkable: true
                checked: sidebar.currentPage === modelData.key
                foreground: checked ? (theme.dark ? theme.colors.text : theme.colors.accent) : theme.colors.secondary
                onClicked: sidebar.navigate(modelData.key)
                background: Rectangle {
                    radius: 9
                    color: parent.checked ? theme.colors.selection : (parent.hovered ? theme.colors.elevated : theme.colors.surface)
                    border.width: parent.visualFocus ? 2 : 0
                    border.color: theme.colors.accent
                }
                ToolTip.visible: hovered
                ToolTip.text: modelData.title + (modelData.ready ? "" : qsTr(" · planned QML page"))
                Accessible.name: modelData.title
            }
        }
        Item { Layout.fillHeight: true }
        UiText { visible: !sidebar.collapsed && sidebar.height > 800; text: qsTr("Installation tools remain available in Existing workflows."); secondary: true; font.pixelSize: 11; Layout.fillWidth: true; Layout.margins: 10 }
        AppButton {
            Layout.fillWidth: true
            text: sidebar.collapsed ? "" : qsTr("Settings")
            iconName: "settings"
            onClicked: sidebar.navigate("settings")
            Accessible.name: qsTr("Settings")
        }
        AppButton {
            Layout.fillWidth: true
            text: sidebar.collapsed ? "" : qsTr("Collapse sidebar")
            iconName: "menu"
            onClicked: sidebar.collapsed = !sidebar.collapsed
            Accessible.name: qsTr("Toggle sidebar")
        }
        UiText { visible: !sidebar.collapsed && sidebar.height > 740; text: "v" + appVersion + "  ·  " + qsTr("Early development"); font.pixelSize: 10; secondary: true; Layout.margins: 10 }
    }
}
