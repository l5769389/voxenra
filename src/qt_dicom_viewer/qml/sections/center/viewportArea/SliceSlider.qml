pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import QtQuick.Controls.Basic as Basic
import "../../../theme"

Item {
    id: root

    required property var viewportController
    readonly property int sliceCount: viewportController?.sliceCount ?? 0
    readonly property int sliceNumber: (viewportController?.sliceIndex ?? 0) + 1

    function selectSlice(index) {
        if (!root.viewportController) return
        root.viewportController.workspaceTab?.activateViewport(root.viewportController.viewportId)
        root.viewportController.setSliceIndex(index)
    }

    implicitWidth: Math.max(32, maximumLabel.implicitWidth + 10)
    property bool allowOrthogonal: false
    visible: !!root.viewportController
        && (root.viewportController.viewportType === "stack" || root.allowOrthogonal)
        && root.sliceCount > 1

    Rectangle {
        anchors.fill: parent
        color: Theme.panelBackground
        radius: 4
    }

    Components.AppButton {
        id: jumpButton
        objectName: "sliceJumpButton"
        anchors.bottom: parent.bottom
        width: parent.width
        implicitHeight: 26
        minimumButtonWidth: 0
        leftPadding: 0
        rightPadding: 0
        text: String(root.sliceNumber)
        fontPixelSize: 11
        Accessible.name: qsTrId("slice.jump")
        Accessible.description: qsTrId("slice.position").arg(root.sliceNumber).arg(root.sliceCount)
        onClicked: jumpPopup.open()
        Components.AppToolTip { visible: jumpButton.hovered; text: qsTrId("slice.jump") }
    }
    Basic.Popup {
        id: jumpPopup
        objectName: "sliceJumpPopup"
        parent: Basic.Overlay.overlay
        popupType: Basic.Popup.Item
        width: Math.min(230, (parent?.width ?? 246) - 16)
        padding: 12
        focus: true
        closePolicy: Basic.Popup.CloseOnEscape | Basic.Popup.CloseOnPressOutside
        onAboutToShow: {
            const point = jumpButton.mapToItem(parent, 0, 0)
            x = Math.max(8, Math.min(point.x, parent.width - width - 8))
            y = Math.max(8, Math.min(point.y - height, parent.height - height - 8))
            sliceInput.text = String(root.sliceNumber)
            sliceInput.forceActiveFocus()
            sliceInput.selectAll()
        }
        function apply() {
            if (!sliceInput.acceptableInput) return
            root.selectSlice(Number(sliceInput.text) - 1)
            close()
        }
        background: Rectangle { color: Theme.elevatedBackground; radius: 6; border.color: Theme.borderStrong }
        contentItem: ColumnLayout {
            Text { text: qsTrId("slice.jump") + " (1–" + root.sliceCount + ")"; color: Theme.textPrimary }
            Components.AppTextField {
                id: sliceInput
                objectName: "sliceNumberInput"
                Layout.fillWidth: true
                Accessible.name: qsTrId("slice.number")
                validator: IntValidator { bottom: 1; top: root.sliceCount }
                onAccepted: jumpPopup.apply()
            }
            Components.AppButton {
                objectName: "sliceJumpApply"
                Layout.fillWidth: true
                text: qsTrId("slice.jump")
                enabled: sliceInput.acceptableInput
                onClicked: jumpPopup.apply()
            }
        }
    }
    onVisibleChanged: if (!visible) jumpPopup.close()

    Text {
        id: minimumLabel
        objectName: "sliceMinimum"
        anchors.top: parent.top
        anchors.topMargin: 3
        anchors.horizontalCenter: parent.horizontalCenter
        height: 20
        text: "1"
        color: Theme.textSecondary
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        TapHandler { onTapped: root.selectSlice(0) }
    }
    Text {
        id: maximumLabel
        objectName: "sliceMaximum"
        anchors.bottom: jumpButton.top
        anchors.bottomMargin: 3
        anchors.horizontalCenter: parent.horizontalCenter
        height: 20
        text: String(root.sliceCount)
        color: Theme.textSecondary
        font.pixelSize: 11
        verticalAlignment: Text.AlignVCenter
        TapHandler { onTapped: root.selectSlice(Math.max(0, root.sliceCount - 1)) }
    }

    Basic.Slider {
        id: sliceControl
        objectName: "sliceControl"
        Accessible.onIncreaseAction: root.selectSlice(Math.min(root.sliceCount - 1, root.sliceNumber))
        Accessible.onDecreaseAction: root.selectSlice(Math.max(0, root.sliceNumber - 2))
        Accessible.name: qsTrId("slice.number")
        Accessible.description: qsTrId("slice.position").arg(root.sliceNumber).arg(root.sliceCount)

        anchors.top: minimumLabel.bottom
        anchors.bottom: maximumLabel.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.topMargin: 4
        anchors.bottomMargin: 4
        leftPadding: 7
        rightPadding: 7

        orientation: Qt.Vertical
        // Rotate the visual control, not its range: accessibility must still
        // report minimum=1, maximum=count, with slice 1 at the top of the rail.
        rotation: 180
        from: 1
        to: Math.max(1, root.sliceCount)
        stepSize: 1
        snapMode: Basic.Slider.SnapAlways
        live: true
        // Depend on the installed range as well as the index: a middle slice
        // may arrive before the count, and Qt otherwise leaves it clamped to 1.
        value: Math.max(1, Math.min(to, root.sliceNumber))
        Keys.onUpPressed: root.selectSlice(Math.max(0, root.sliceNumber - 2))
        Keys.onDownPressed: root.selectSlice(Math.min(root.sliceCount - 1, root.sliceNumber))
        onValueChanged: Qt.callLater(function() {
            // Accessible value setters do not emit moved(). Wait for range and
            // controller bindings to settle before forwarding an external value.
            if (!sliceControl.pressed && root.sliceCount > 0
                    && Math.round(sliceControl.value) !== Math.max(1, Math.min(root.sliceCount, root.sliceNumber)))
                root.selectSlice(Math.round(sliceControl.value) - 1)
        })

        onMoved: {
            if (!root.viewportController)
                return
            root.selectSlice(Math.round(sliceControl.value) - 1)
        }

        Components.AppToolTip {
            visible: sliceControl.hovered || sliceControl.pressed
            delay: 250
            text: Math.round(sliceControl.value)
                + " / " + (root.viewportController
                    ? root.viewportController.sliceCount
                    : 0)
        }

        background: Rectangle {
            x: sliceControl.leftPadding
                + (sliceControl.availableWidth - width) / 2
            y: sliceControl.topPadding
            width: 4
            height: sliceControl.availableHeight
            radius: 2
            color: Theme.controlBackground
            border.width: 1
            border.color: Theme.controlBorder

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: sliceControl.position
                    * parent.height
                radius: parent.radius
                color: Theme.primaryStrong
            }
        }

        handle: Rectangle {
            x: sliceControl.leftPadding
                + (sliceControl.availableWidth - width) / 2
            y: sliceControl.topPadding
                + sliceControl.visualPosition
                    * (sliceControl.availableHeight - height)
            implicitWidth: 14
            implicitHeight: 14
            radius: width / 2
            color: sliceControl.pressed
                ? Theme.primaryPressed
                : sliceControl.hovered
                    ? Theme.primaryHover
                    : Theme.primaryColor
            border.width: 1
            border.color: Theme.textOnPrimary
        }
    }
}
