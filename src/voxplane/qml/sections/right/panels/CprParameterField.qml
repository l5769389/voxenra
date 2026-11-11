pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

RowLayout {
    id: row
    required property var controller
    required property string parameter
    Layout.fillWidth: true
    Text {
        Layout.fillWidth: true
        Layout.minimumWidth: 0
        text: qsTrId("cpr." + row.parameter)
        wrapMode: Text.Wrap
        font.pixelSize: 12
        color: row.enabled ? Theme.textSecondary : Theme.textDisabled
    }
    Components.AppNumberField {
        objectName: "cprParameter-" + row.parameter
        Layout.preferredWidth: 82
        Accessible.name: qsTrId("cpr." + row.parameter)
        numberValue: Number(row.controller?.parameters[row.parameter] ?? 0)
        readonly property var limits: row.controller?.parameterLimits ?? ({})
        minimum: row.parameter === "angle" ? -360
            : row.parameter === "step" ? limits.minStep ?? 0.05
            : ["width", "crossWidth"].includes(row.parameter) ? 0.01 : 0
        maximum: {
            switch (row.parameter) {
            case "angle": return 360
            case "step": return limits.maxStep ?? 10
            case "thickness": return limits.maxThickness ?? 100
            case "width": case "crossWidth": return limits.maxWidth ?? 500
            default: return row.controller?.totalLength ?? 0
            }
        }
        color: activeFocus && !acceptableInput ? Theme.warningColor : enabled ? Theme.textPrimary : Theme.textDisabled
        placeholderText: minimum + "–" + Number(maximum.toFixed(2))
        Accessible.description: qsTrId("cpr.validRange").arg(minimum).arg(Number(maximum.toFixed(2)))
        decimals: 2
        editContext: [row.controller, row.controller?.selectedPathId, row.parameter]
        onEdited: value => row.controller?.setParameter(row.parameter, value)
    }
}
