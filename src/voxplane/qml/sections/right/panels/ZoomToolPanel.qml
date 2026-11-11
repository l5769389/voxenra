pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"
import QtQuick.Controls.Basic as Basic

ColumnLayout {
    id: panel
    objectName: "zoomToolPanel"
    required property var viewportController
    readonly property real current: viewportController?.zoom ?? 1
    readonly property bool ready: !!viewportController
        && (viewportController.loadState === "ready" || (viewportController.sliceCount ?? 0) > 0)
    spacing: 8
    readonly property var bindings: typeof appController !== "undefined" ? appController.shortcutController?.bindings ?? [] : []
    readonly property var zoomKeys: bindings.filter(b => b.menu === "zoom")
    readonly property bool defaultKeys: zoomKeys.length === 10
        && zoomKeys.every(b => b.sequence === String(Number(b.action.slice(5)) % 10))
    readonly property string keysHelp: zoomKeys.filter(b => b.display)
        .map(b => b.action.slice(5) + "× (" + b.display + ")").join(" · ")
    Components.PanelHeading {
        objectName: "zoomHeading"
        title: I18n.format(qsTrId("zoom.current"), {zoom: Number(panel.current.toFixed(2))})
        explanation: panel.defaultKeys ? "" : panel.keysHelp
    }
    Components.AppSlider {
        id: slider
        objectName: "zoomSlider"
        Layout.fillWidth: true
        enabled: panel.ready
        focusPolicy: Qt.StrongFocus
        from: 0.1
        to: 20
        stepSize: 0.1
        snapMode: Basic.Slider.SnapAlways
        value: panel.current
        Accessible.name: qsTrId("input.action.zoom")
        Accessible.description: qsTrId("text.1023")
        onMoved: panel.viewportController.setZoom(Number(value.toFixed(1)))
        // Assistive clients set the value directly, without emitting moved().
        onValueChanged: Qt.callLater(syncExternalValue)
        function syncExternalValue() {
            if (panel.ready && !pressed && Math.abs(value - panel.current) > 0.000001)
                panel.viewportController.setZoom(value)
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Text { text: "0.1×"; color: Theme.textMuted; font.pixelSize: 11 }
        Item { Layout.fillWidth: true }
        Text { text: "20×"; color: Theme.textMuted; font.pixelSize: 11 }
    }
    Text {
        Layout.fillWidth: true
        text: qsTrId(panel.defaultKeys ? "zoom.fitKeys" : "text.1023")
        color: Theme.textSubtle
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }
}
