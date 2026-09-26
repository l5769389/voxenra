pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
import "../../../theme"
import "../../../components" as Components
import "../components" as Controls

ColumnLayout {
    id: annotatePanel
    objectName: "annotatePanel"
    required property var viewportController
    readonly property var controller: annotatePanel.viewportController ? annotatePanel.viewportController.textAnnotationController : null
    readonly property var settingsController: viewportController.settingsController
    readonly property var styleSettings: settingsController?.values.measurement ?? ({})
    readonly property bool textMode: viewportController.activeInteraction === "annotate:text"
    readonly property bool selectedArrow: (viewportController.measurementController?.measurementItems ?? []).some(
        item => item.type === "arrow" && item.measurementId === viewportController.measurementController.selectedMeasurementId)
    spacing: 12

    RowLayout {
        Layout.fillWidth: true
        Controls.ToolActionButton {
            objectName: "annotateArrowMode"
            Layout.fillWidth: true
            compact: true
            momentary: true
            label: qsTrId("text.0377")
            iconName: "annotate-arrow"
            checked: annotatePanel.viewportController.activeInteraction === "annotate:arrow"
            onClicked: annotatePanel.viewportController.setAnnotationMode(false)
        }
        Controls.ToolActionButton {
            objectName: "annotateTextMode"
            Layout.fillWidth: true
            compact: true
            momentary: true
            label: qsTrId("text.0378")
            iconName: "annotate-text"
            checked: annotatePanel.viewportController.activeInteraction === "annotate:text"
            onClicked: annotatePanel.viewportController.setAnnotationMode(true)
        }
    }

    Text {
        Layout.fillWidth: true
        text: (annotatePanel.textMode ? qsTrId("text.1114") : qsTrId("text.1115"))
            + "\n" + I18n.format(qsTrId("annotation.copyHint"), {keys: Qt.platform.os === "osx" ? "⌘+C / ⌘+V" : "Ctrl+C / Ctrl+V"})
            + (Qt.platform.os === "osx" ? qsTrId("text.1117") : qsTrId("text.1118"))
        color: Theme.textSubtle
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }

    Text {
        visible: annotatePanel.textMode
        text: qsTrId("text.0180")
        color: Theme.textSecondary
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }

    Basic.ScrollView {
        visible: annotatePanel.textMode
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        Layout.preferredHeight: 84
        contentWidth: availableWidth
        clip: true
        Basic.ScrollBar.vertical: Components.AppScrollBar {}
        Basic.ScrollBar.horizontal.policy: Basic.ScrollBar.AlwaysOff
        Basic.TextArea {
            id: annotationEditor
            objectName: "annotationTextEditor"
            text: annotatePanel.controller ? annotatePanel.controller.annotationText : ""
            color: Theme.textPrimary
            placeholderText: qsTrId("text.1119")
            placeholderTextColor: Theme.textDisabled
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            font.pixelSize: 13
            leftPadding: 9
            rightPadding: 9
            topPadding: 7
            bottomPadding: 7

            onTextChanged: {
                if (activeFocus && annotatePanel.controller) {
                    annotatePanel.viewportController.setAnnotationMode(true);
                    annotatePanel.controller.setAnnotationText(text);
                }
            }

            background: Rectangle {
                color: Theme.controlBackground
                border.color: annotationEditor.activeFocus ? Theme.focusBorder : Theme.inputBorder
                radius: Theme.controlRadius
            }

            Connections {
                target: annotatePanel.controller
                function onEditorChanged() {
                    if (annotationEditor.text !== annotatePanel.controller.annotationText) {
                        annotationEditor.text = annotatePanel.controller.annotationText;
                    }
                }
            }
        }
    }

    Text {
        text: qsTrId("text.0839")
        color: Theme.textSecondary
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }

    Row {
        id: colorPalette
        objectName: "annotationColors"
        readonly property real swatchSize: Math.max(24, Math.min(28, Math.floor((width - 6 * spacing) / 7)))
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        spacing: 2

        Repeater {
            model: Theme.annotationSwatches

            delegate: Basic.Button {
                id: colorButton
                hoverEnabled: true
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                required property string modelData
                objectName: "annotationColor-" + modelData.slice(1)
                width: colorPalette.swatchSize
                height: width
                Accessible.name: qsTrId("text.1120") + modelData
                checked: (annotatePanel.textMode
                    ? annotatePanel.controller?.annotationColor
                    : annotatePanel.styleSettings.annotationColor) === modelData
                onClicked: {
                    if (annotatePanel.textMode)
                        annotatePanel.controller?.setAnnotationColor(modelData)
                    else
                        annotatePanel.settingsController?.setValue("measurement", "annotationColor", modelData)
                }

                background: Rectangle {
                    radius: width / 2
                    color: colorButton.down ? Qt.darker(colorButton.modelData, 1.3)
                        : colorButton.hovered ? Qt.lighter(colorButton.modelData, 1.15) : colorButton.modelData
                    border.width: colorButton.checked || colorButton.hovered ? 3 : 1
                    border.color: colorButton.down ? Theme.primaryColor
                        : colorButton.hovered ? Theme.textPrimary
                        : colorButton.checked ? Theme.selectionBorder : Theme.controlBorder
                    Behavior on color { ColorAnimation { duration: 80 } }
                }
            }
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Text {
            text: qsTrId("text.0771")
            color: Theme.textSecondary
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        Components.AppSlider {
            id: lineWidthSlider
            objectName: "annotationLineWidth"
            Layout.fillWidth: true
            from: 1
            to: 6
            stepSize: 0.5
            value: annotatePanel.styleSettings.lineWidth ?? 1.5
            Accessible.name: qsTrId("text.1121")
            onMoved: annotatePanel.settingsController?.setValue("measurement", "lineWidth", value)
        }
        Text {
            Layout.preferredWidth: 42
            horizontalAlignment: Text.AlignRight
            text: lineWidthSlider.value + " px"
            color: Theme.textPrimary
            font.pixelSize: 12
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 8
        Text {
            text: qsTrId("text.1122")
            color: Theme.textSecondary
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
        Components.AppSlider {
            id: arrowSizeSlider
            objectName: "annotationArrowSize"
            Layout.fillWidth: true
            from: 8
            to: 28
            stepSize: 1
            value: annotatePanel.styleSettings.annotationSize ?? 14
            Accessible.name: qsTrId("text.1123")
            onMoved: annotatePanel.settingsController?.setValue("measurement", "annotationSize", Math.round(value))
        }
        Text {
            Layout.preferredWidth: 42
            horizontalAlignment: Text.AlignRight
            text: Math.round(arrowSizeSlider.value) + " px"
            color: Theme.textPrimary
            font.pixelSize: 12
        }
    }

    RowLayout {
        visible: annotatePanel.textMode
        Layout.fillWidth: true
        spacing: 10

        Text {
            text: qsTrId("text.1124")
            color: Theme.textSecondary
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }

        Components.AppSlider {
            id: fontSizeSlider
            objectName: "annotationFontSize"
            Layout.fillWidth: true
            from: 10
            to: 48
            stepSize: 1
            value: annotatePanel.controller ? annotatePanel.controller.annotationFontSize : 16
            onMoved: annotatePanel.controller?.setAnnotationFontSize(Math.round(value))
        }

        Text {
            Layout.preferredWidth: 38
            horizontalAlignment: Text.AlignRight
            text: Math.round(fontSizeSlider.value) + " px"
            color: Theme.textPrimary
            font.pixelSize: 12
        }
    }

    Components.AppButton {
        objectName: "deleteSelectedAnnotation"
        Layout.fillWidth: true
        text: qsTrId("text.1125")
        compact: true
        hoverColor: Theme.resetActionHover
        enabled: annotatePanel.textMode ? (annotatePanel.controller?.hasSelection ?? false) : annotatePanel.selectedArrow
        onClicked: annotatePanel.viewportController.deleteSelectedMeasurement()
    }

    Item { Layout.fillHeight: true }
}
