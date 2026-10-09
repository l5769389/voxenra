pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components

ColumnLayout {
    id: pseudoColorPanel
    objectName: "pseudoColorPanel"
    required property var viewportController
    property string buttonPrefix: "colorMap-"
    signal colorSelected()
    property string description: qsTrId("text.1068")
    spacing: 6

    Components.PanelHeading {
        objectName: "PseudoColorPanelHeading"
        title: qsTrId("text.0309")
        explanation: pseudoColorPanel.description
    }


    Repeater {
        model: pseudoColorPanel.viewportController
            ? pseudoColorPanel.viewportController.colorMapOptions : []

        delegate: Components.AppButton {
            id: colorMapButton
            required property var modelData
            objectName: pseudoColorPanel.buttonPrefix + modelData.colorMap
            Layout.fillWidth: true
            implicitHeight: 36
            topPadding: 6
            bottomPadding: 6
            Layout.minimumWidth: 0
            checked: pseudoColorPanel.viewportController
                && pseudoColorPanel.viewportController.activeColorMap
                    === modelData.colorMap
            onClicked: {
                pseudoColorPanel.viewportController?.applyColorMap(modelData.colorMap)
                pseudoColorPanel.colorSelected()
            }

            contentItem: RowLayout {
                spacing: 10

                Canvas {
                    id: gradientPreview
                    Layout.preferredWidth: Math.min(80, colorMapButton.width * 0.3)
                    Layout.preferredHeight: 16

                    onWidthChanged: requestPaint()
                    onHeightChanged: requestPaint()
                    onPaint: {
                        const context = getContext("2d")
                        context.reset()
                        const gradient = context.createLinearGradient(
                            0, 0, width, 0
                        )
                        for (const stop of colorMapButton.modelData.stops)
                            gradient.addColorStop(stop.position, stop.color)
                        context.fillStyle = gradient
                        context.fillRect(0, 0, width, height)
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: colorMapButton.modelData.label
                    color: colorMapButton.checked
                        ? Theme.textPrimary : Theme.textSecondary
                    Layout.minimumWidth: 0
                    elide: Text.ElideRight
                    verticalAlignment: Text.AlignVCenter
                    font.pixelSize: 12
                    font.weight: colorMapButton.checked
                        ? Font.DemiBold : Font.Normal
                }

                Text {
                    visible: colorMapButton.checked
                    text: "✓"
                    color: Theme.iconActive
                    font.pixelSize: 16
                    font.bold: true
                }
            }

            normalColor: "transparent"
            cornerRadius: 5
        }
    }

    Item { Layout.fillHeight: true }
}
