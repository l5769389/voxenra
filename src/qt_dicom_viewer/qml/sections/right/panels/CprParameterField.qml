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
        minimum: row.parameter === "angle" ? -360 : 0
        maximum: 10000
        decimals: 2
        editContext: [row.controller, row.parameter]
        onEdited: value => row.controller?.setParameter(row.parameter, value)
    }
}
