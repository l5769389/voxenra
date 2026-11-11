pragma ComponentBehavior: Bound
import QtQuick

Item {
    id: root
    objectName: "mprCrosshairLayer"
    clip: true

    required property var crosshairStyle
    required property point crosshairPosition
    required property real rotationDegrees
    property real centerX: root.crosshairPosition.x
    property real centerY: root.crosshairPosition.y

    // A viewport can release its controller before this visual layer retires.
    property real centerGap: root.crosshairStyle?.centerGap ?? 0
    property real lineWidth: root.crosshairStyle?.lineWidth ?? 0
    property real horizontalWidth: root.crosshairStyle?.horizontalWidth ?? lineWidth
    property real verticalWidth: root.crosshairStyle?.verticalWidth ?? lineWidth
    property color horizontalColor: root.crosshairStyle?.horizontalColor ?? "transparent"
    property color verticalColor: root.crosshairStyle?.verticalColor ?? "transparent"
    property real armLength: root.crosshairStyle?.armLength ?? 2 * Math.hypot(root.width, root.height)
    readonly property real outlineWidth: root.crosshairStyle?.outlineWidth ?? 0
    readonly property color outlineColor: root.crosshairStyle?.outlineColor ?? "black"

    component LocatorArm: Item {
        id: arm
        required property color color
        Rectangle {
            anchors.fill: parent
            anchors.margins: -root.outlineWidth
            color: root.outlineColor
            visible: root.outlineWidth > 0
        }
        Rectangle {
            anchors.fill: parent
            color: arm.color
        }
    }

    Item {
        anchors.fill: parent

        transform: Rotation {
            origin.x: root.centerX
            origin.y: root.centerY
            angle: root.rotationDegrees
        }

        LocatorArm {
            x: root.centerX - root.centerGap / 2 - root.armLength
            y: root.centerY - root.horizontalWidth / 2
            width: root.armLength
            height: root.horizontalWidth
            color: root.horizontalColor
        }

        LocatorArm {
            x: root.centerX + root.centerGap / 2
            y: root.centerY - root.horizontalWidth / 2
            width: root.armLength
            height: root.horizontalWidth
            color: root.horizontalColor
        }

        LocatorArm {
            x: root.centerX - root.verticalWidth / 2
            y: root.centerY - root.centerGap / 2 - root.armLength
            width: root.verticalWidth
            height: root.armLength
            color: root.verticalColor
        }

        LocatorArm {
            x: root.centerX - root.verticalWidth / 2
            y: root.centerY + root.centerGap / 2
            width: root.verticalWidth
            height: root.armLength
            color: root.verticalColor
        }
    }
}
