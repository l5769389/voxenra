pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Window
import "../theme"

Item {
    id: appIcon
    required property string iconName
    property real iconSize: 20
    property color iconColor: Theme.iconDefault
    property color detailColor: "transparent"
    readonly property real pixelRatio: Math.max(1, Screen.devicePixelRatio)
    readonly property bool isPseudocolorIcon: ["pseudocolor", "pseudocolor-gray"].includes(iconName)
    readonly property bool isSvgIcon: !isPseudocolorIcon
    implicitWidth: iconSize
    implicitHeight: iconSize
    width: iconSize
    height: iconSize
    Image {
        objectName: "navigationSvgIcon"
        anchors.fill: parent
        visible: appIcon.isSvgIcon
        source: visible ? "image://navigation/" + appIcon.iconName + "/"
            + encodeURIComponent(appIcon.iconColor.toString()) + "/" + encodeURIComponent(appIcon.detailColor.toString()) : ""
        sourceSize.width: Math.ceil(appIcon.width * appIcon.pixelRatio)
        sourceSize.height: Math.ceil(appIcon.height * appIcon.pixelRatio)
        smooth: true
        mipmap: true
    }
    ColorMapIcon {
        objectName: "pseudocolorIcon"
        anchors.fill: parent
        visible: appIcon.isPseudocolorIcon
        tint: appIcon.iconColor
    }
}
