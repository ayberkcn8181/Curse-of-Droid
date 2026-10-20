import QtQuick
import QtQuick.Controls

Label {
    property bool secondary: false
    color: secondary ? theme.colors.secondary : theme.colors.text
    font.pixelSize: 14 * theme.scale
    textFormat: Text.PlainText
    wrapMode: Text.WordWrap
    verticalAlignment: Text.AlignVCenter
    Accessible.name: text
}
