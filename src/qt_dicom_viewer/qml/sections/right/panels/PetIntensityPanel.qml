pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls.Basic as Basic
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: petPanel
    objectName: "petIntensityPanel"

    required property var viewportController
    spacing: 12

    function formatValue(value) {
        if (!Number.isFinite(value))
            return "--"
        const precision = Math.abs(value) >= 1000 ? 0
            : Math.abs(value) >= 10 ? 2 : 3
        const result = Number(value).toFixed(precision)
        return precision === 0 ? result : result.replace(/\.?0+$/, "")
    }

    Text {
        text: qsTrId("text.1146")
        color: Theme.textPrimary
        font.pixelSize: 14
        font.weight: Font.DemiBold
    }
    Text {
        visible: petPanel.viewportController ? petPanel.viewportController.petUnitPending : false
        text: qsTrId("text.1147")
        color: Theme.textMuted
        font.pixelSize: 12
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: rangeContent.implicitHeight + 24
        color: Theme.cardBackground
        border.color: Theme.borderSubtle
        radius: 8

        ColumnLayout {
            id: rangeContent
            anchors.fill: parent
            anchors.margins: 12
            spacing: 10

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.1148")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }

                Components.AppNumberField {
                    id: displayUpperInput
                    objectName: "petDisplayUpperInput"
                    Layout.preferredWidth: 92; implicitHeight: 32
                    horizontalAlignment: Text.AlignRight
                    minimum: petPanel.viewportController ? petPanel.viewportController.petMinimumUpper : 0.001
                    maximum: 1e12; decimals: 3
                    numberValue: petPanel.viewportController ? petPanel.viewportController.petDisplayUpper : 0
                    onEdited: value => petPanel.viewportController.setPetDisplayUpper(value)
                }

            }

            Basic.Slider {
                id: displayUpperSlider
                objectName: "petDisplayUpperSlider"
                Layout.fillWidth: true
                from: petPanel.viewportController
                    ? petPanel.viewportController.petMinimumUpper
                    : 0.001
                to: Math.max(
                    from,
                    petPanel.viewportController
                        ? petPanel.viewportController.petControlUpper
                        : 1
                )
                value: petPanel.viewportController
                    ? petPanel.viewportController.petDisplayUpper
                    : 0
                onMoved: petPanel.viewportController.setPetDisplayUpper(value)

                background: Rectangle {
                    x: displayUpperSlider.leftPadding
                    y: displayUpperSlider.topPadding
                        + displayUpperSlider.availableHeight / 2 - height / 2
                    width: displayUpperSlider.availableWidth
                    height: 14
                    radius: 5
                    border.color: Theme.borderStrong
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Theme.intensityBlack }
                        GradientStop { position: 1; color: Theme.intensityWhite }
                    }
                }

                handle: Rectangle {
                    x: displayUpperSlider.leftPadding
                        + displayUpperSlider.visualPosition
                        * (displayUpperSlider.availableWidth - width)
                    y: displayUpperSlider.topPadding
                        + displayUpperSlider.availableHeight / 2 - height / 2
                    width: 16
                    height: 26
                    radius: 6
                    color: Theme.primaryColor
                    border.color: Theme.textOnPrimary
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.1149")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }

                Components.AppNumberField {
                    objectName: "petControlUpperInput"
                    // Partial digits must not repeatedly clamp the PET display
                    // upper limit while editing the slider's allowed range.
                    commitOnFinish: true
                    Layout.preferredWidth: 92
                    implicitHeight: 32
                    horizontalAlignment: Text.AlignRight
                    numberValue: petPanel.viewportController ? petPanel.viewportController.petControlUpper : 0
                    color: Theme.textPrimary
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    minimum: 0.001; maximum: 1e12; decimals: 3
                    onEdited: value => petPanel.viewportController.setPetControlUpper(value)
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: petPanel.width < 240 ? 4 : 5
                columnSpacing: 6
                rowSpacing: 6

                Repeater {
                    model: petPanel.viewportController
                        ? petPanel.viewportController.petControlUpperOptions
                        : []

                    delegate: Components.AppButton {
                        required property var modelData
                        Layout.fillWidth: true
                        compact: true
                        checkable: true
                        checked: petPanel.viewportController !== null && Math.abs(
                            Number(modelData)
                            - petPanel.viewportController.petControlUpper
                        ) < 0.000001
                        text: petPanel.formatValue(Number(modelData))
                        onClicked: petPanel.viewportController.setPetControlUpper(
                            Number(modelData)
                        )
                    }
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: unitContent.implicitHeight + 24
        color: Theme.cardBackground
        border.color: Theme.borderSubtle
        radius: 8

        ColumnLayout {
            id: unitContent
            anchors.fill: parent
            anchors.margins: 12
            spacing: 10

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: qsTrId("text.1150")
                    color: Theme.textMuted
                    font.pixelSize: 12
                }

                Text {
                    text: petPanel.viewportController
                        ? petPanel.viewportController.petActiveUnitLabel
                        : ""
                    color: Theme.textPrimary
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }

            GridLayout {
                Layout.fillWidth: true
                columns: petPanel.width < 260 ? 1 : 2
                columnSpacing: 8
                rowSpacing: 8

                Repeater {
                    model: petPanel.viewportController
                        ? petPanel.viewportController.petUnitOptions
                        : []

                    delegate: Components.AppButton {
                        required property var modelData
                        objectName: "petUnit-" + modelData.unitId
                        id: unitButton
                        Layout.fillWidth: true
                        checkable: true
                        checked: modelData.active
                        enabled: modelData.enabled
                        text: modelData.label
                        fontPixelSize: 11
                        onClicked: petPanel.viewportController.setPetUnit(
                            modelData.unitId
                        )
                        Components.AppToolTip {
                            visible: unitButton.hovered
                                && unitButton.modelData.warning !== ""
                            delay: 350
                            text: unitButton.modelData.warning
                        }
                    }
                }
            }
        }
    }

}
