import QtQuick
import "../../../theme"

pragma ComponentBehavior: Bound

Item {
    id: directionOverlay

    required property var directionLabels
    readonly property int directionMargin: 4
    readonly property real horizontalLabelWidth: Math.max(topDirection.implicitWidth, bottomDirection.implicitWidth)

    component DirectionText: Text {
        visible: text.length > 0
        color: Theme.overlayText
        font.pixelSize: 14
        font.weight: Font.DemiBold
        style: Text.Outline
        styleColor: Theme.overlayOutline
    }

    DirectionText {
        id: topDirection
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: directionOverlay.directionMargin
        text: directionOverlay.directionLabels.top ?? ""
    }

    DirectionText {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        anchors.rightMargin: directionOverlay.directionMargin
        text: directionOverlay.directionLabels.right ?? ""
    }

    DirectionText {
        id: bottomDirection
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: directionOverlay.directionMargin
        text: directionOverlay.directionLabels.bottom ?? ""
    }

    DirectionText {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        anchors.leftMargin: directionOverlay.directionMargin
        text: directionOverlay.directionLabels.left ?? ""
    }
}
