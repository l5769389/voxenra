pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "displayMappingPanel"
    required property var viewportController
    readonly property var mapping: viewportController?.displayMapping ?? ({})
    property bool backgroundExpanded: false
    spacing: 12

    Components.PanelHeading {
        objectName: "ScalarMappingPanelHeading"
        title: qsTrId("mapping.title")
        explanation: panel.mapping.kind === "palette" ? qsTrId("mapping.paletteHint") : qsTrId("mapping.rangeHint")
    }
    RowLayout {
        Layout.fillWidth: true
        Components.AppButton {
            objectName: "mappingSource"
            Layout.fillWidth: true
            text: qsTrId("mapping.source")
            checkable: true
            checked: panel.mapping.mode === "source"
            onClicked: panel.viewportController.setDisplayMappingMode("source")
        }
        Components.AppButton {
            objectName: "mappingCustom"
            Layout.fillWidth: true
            text: qsTrId("mapping.custom")
            checkable: true
            checked: panel.mapping.mode === "custom"
            enabled: panel.mapping.canCustomize === true
            onClicked: panel.viewportController.setDisplayMappingMode("custom")
        }
    }

    Text {
        objectName: "mappingUnit"
        text: qsTrId("mapping.unit") + ": " + (panel.mapping.unit || "—")
        color: Theme.textPrimary
        font.pixelSize: 12
    }
    Canvas {
        id: colorBar
        objectName: "mappingColorBar"
        Layout.fillWidth: true
        Layout.preferredHeight: 18
        readonly property var colors: panel.mapping.colors ?? []
        onColorsChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            const context = getContext("2d")
            context.clearRect(0, 0, width, height)
            const gradient = context.createLinearGradient(0, 0, width, 0)
            for (let i = 0; i < colors.length; ++i)
                gradient.addColorStop(i / Math.max(1, colors.length - 1), colors[i])
            context.fillStyle = gradient
            context.fillRect(0, 0, width, height)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text { text: Number(panel.mapping.lower ?? 0).toFixed(3).replace(/\.?0+$/, ""); color: Theme.textMuted; font.pixelSize: 12 }
        Item { Layout.fillWidth: true }
        Text { text: Number(panel.mapping.upper ?? 1).toFixed(3).replace(/\.?0+$/, ""); color: Theme.textMuted; font.pixelSize: 12 }
    }
    RowLayout {
        visible: panel.mapping.mode === "custom"
        Layout.fillWidth: true
        ColumnLayout {
            Layout.fillWidth: true
            Text { text: qsTrId("mapping.lower"); color: Theme.textMuted; font.pixelSize: 12 }
            Components.AppNumberField {
                objectName: "mappingLower"
                Layout.fillWidth: true
                minimum: -1e12; maximum: 1e12; decimals: 3; commitOnFinish: true
                numberValue: panel.mapping.lower ?? 0
                onEdited: value => panel.viewportController.setDisplayRange(value, panel.mapping.upper)
            }
        }
        ColumnLayout {
            Layout.fillWidth: true
            Text { text: qsTrId("mapping.upper"); color: Theme.textMuted; font.pixelSize: 12 }
            Components.AppNumberField {
                objectName: "mappingUpper"
                Layout.fillWidth: true
                minimum: -1e12; maximum: 1e12; decimals: 3; commitOnFinish: true
                numberValue: panel.mapping.upper ?? 1
                onEdited: value => panel.viewportController.setDisplayRange(panel.mapping.lower, value)
            }
        }
    }
    Text {
        visible: !!panel.mapping.warning
        Layout.fillWidth: true
        text: panel.mapping.warning ?? ""
        color: Theme.textMuted; font.pixelSize: 12; wrapMode: Text.WordWrap
    }
    Components.AppButton {
        objectName: "mappingBackground"
        visible: panel.mapping.grayscaleBackground === true
        Layout.fillWidth: true
        text: qsTrId("mapping.background") + (panel.backgroundExpanded ? " −" : " +")
        onClicked: panel.backgroundExpanded = !panel.backgroundExpanded
    }
    Loader {
        Layout.fillWidth: true
        active: panel.backgroundExpanded && panel.mapping.grayscaleBackground === true
        sourceComponent: Component {
            WindowLevelToolPanel {
                description: qsTrId("ct.paletteHint")
                currentCenter: panel.viewportController.windowCenter
                currentWidth: panel.viewportController.windowWidth
                allowTemplates: false
                presets: []
                supportsInversion: true
                inverted: panel.viewportController.inverted
                onInversionRequested: panel.viewportController.toggleInverted()
                onActionTriggered: (id, center, width) => panel.viewportController.applyWindowPreset(center, width)
            }
        }
    }

}
