pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components

ColumnLayout {
    id: mipPanel
    objectName: "mipPanel"

    required property var toolController
    spacing: 14

    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 34

        Text {
            Layout.fillWidth: true
            text: qsTrId("text.1071")
            color: Theme.textSecondary
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 2.5
        }

        Basic.Switch {
            id: enabledSwitch
            objectName: "mipEnabledSwitch"

            implicitWidth: 44
            implicitHeight: 24
            checked: mipPanel.toolController
                ? mipPanel.toolController.mprProjectionEnabled
                : false
            onClicked: {
                mipPanel.toolController?.setMprProjectionEnabled(checked)
            }

            indicator: Rectangle {
                implicitWidth: 44
                implicitHeight: 24
                radius: 12
                color: enabledSwitch.checked
                    ? Theme.primaryStrong
                    : Theme.controlBackground
                border.color: enabledSwitch.checked
                    ? Theme.primaryColor
                    : Theme.borderStrong
                border.width: 1

                Rectangle {
                    x: enabledSwitch.checked
                        ? parent.width - width - 3
                        : 3
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18
                    height: 18
                    radius: 9
                    color: enabledSwitch.checked
                        ? Theme.textOnPrimary
                        : Theme.textMuted

                    Behavior on x {
                        NumberAnimation {
                            duration: 120
                            easing.type: Easing.OutCubic
                        }
                    }
                }
            }

            contentItem: Item {}
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 6

        Repeater {
            model: [
                { value: "mip", label: "MIP" },
                { value: "minip", label: "MinIP" },
                { value: "mean", label: "Mean" },
                { value: "sum", label: "Sum" }
            ]

            delegate: Components.AppButton {
                id: modeButton
                required property var modelData

                objectName: "mipMode-" + modelData.value
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                implicitHeight: 36
                checkable: true
                checked: mipPanel.toolController
                    ? mipPanel.toolController.mprProjectionMode
                        === modelData.value
                    : false

                contentItem: Text {
                    text: modeButton.modelData.label
                    color: modeButton.checked
                        ? Theme.primaryColor
                        : Theme.textSecondary
                    font.pixelSize: 12
                    font.weight: modeButton.checked
                        ? Font.DemiBold
                        : Font.Medium
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }

                normalColor: "transparent"
                activeColor: Theme.primarySoft
                baseBorderWidth: 1
                baseBorderColor: Theme.controlBorder
                cornerRadius: 8

                onClicked: {
                    mipPanel.toolController?.setMprProjectionMode(
                        modelData.value
                    )
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        color: Theme.dividerColor
    }

    Repeater {
        model: [
            {
                plane: "axial",
                label: qsTrId("plane.axial"),
                color: Theme.axisAxial
            },
            {
                plane: "coronal",
                label: qsTrId("plane.coronal"),
                color: Theme.axisCoronal
            },
            {
                plane: "sagittal",
                label: qsTrId("plane.sagittal"),
                color: Theme.axisSagittal
            }
        ]

        delegate: ColumnLayout {
            id: axisSection
            required property var modelData

            Layout.fillWidth: true
            Layout.preferredHeight: 104
            spacing: 8

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: axisSection.modelData.label
                    color: axisSection.modelData.color
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    font.letterSpacing: 0.4
                }

                Rectangle {
                    Layout.preferredWidth: 88
                    Layout.preferredHeight: 32
                    color: "transparent"
                    border.color: Theme.controlBorder
                    border.width: 1
                    radius: 16

                    Components.AppNumberField {
                        id: thicknessInput
                        objectName: "mipThicknessInput-" + axisSection.modelData.plane
                        anchors.fill: parent
                        leftPadding: 10; rightPadding: 27
                        horizontalAlignment: Text.AlignHCenter
                        minimum: 0; maximum: 100; decimals: 0
                        numberValue: thicknessSlider.value
                        onEdited: value => mipPanel.toolController?.setMprThickness(axisSection.modelData.plane, value)
                        background: Item {}
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: "MM"
                        color: Theme.textMuted
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        font.letterSpacing: 1
                    }
                }
            }

            Basic.Slider {
                id: thicknessSlider
                objectName: "mipThickness-" + axisSection.modelData.plane

                Layout.fillWidth: true
                implicitHeight: 22
                from: 0
                to: 100
                stepSize: 1
                live: true
                value: mipPanel.toolController
                    ? Number(
                        mipPanel.toolController.mprThicknesses[
                            axisSection.modelData.plane
                        ] ?? 0
                    )
                    : 0

                onMoved: {
                    thicknessInput.text = String(Math.round(value))
                    mipPanel.toolController?.setMprThickness(
                        axisSection.modelData.plane,
                        value
                    )
                }

                background: Item {
                    x: thicknessSlider.leftPadding
                    y: thicknessSlider.topPadding
                        + thicknessSlider.availableHeight / 2 - height / 2
                    width: thicknessSlider.availableWidth
                    height: 7

                    Rectangle {
                        anchors.fill: parent
                        radius: 3.5
                        color: "transparent"
                        border.color: Theme.borderStrong
                        border.width: 1
                    }

                    Rectangle {
                        width: thicknessSlider.visualPosition * parent.width
                        height: parent.height
                        radius: 3.5
                        color: axisSection.modelData.color
                        opacity: mipPanel.toolController
                            && mipPanel.toolController.mprProjectionEnabled
                            ? 0.9
                            : 0.55
                    }
                }

                handle: Rectangle {
                    x: thicknessSlider.leftPadding
                        + thicknessSlider.visualPosition
                        * (thicknessSlider.availableWidth - width)
                    y: thicknessSlider.topPadding
                        + thicknessSlider.availableHeight / 2 - height / 2
                    implicitWidth: 16
                    implicitHeight: 16
                    radius: 8
                    color: axisSection.modelData.color
                    border.color: Theme.textOnPrimary
                    border.width: 2

                    Rectangle {
                        anchors.centerIn: parent
                        width: 3
                        height: 3
                        radius: 1.5
                        color: Theme.textOnPrimary
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: "0 mm"
                    color: Theme.textSubtle
                    font.pixelSize: 10
                }

                Text {
                    text: "100 mm"
                    color: Theme.textSubtle
                    font.pixelSize: 10
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: Theme.dividerColor
                opacity: 0.7
            }
        }
    }

    Item {
        Layout.fillHeight: true
    }
}
