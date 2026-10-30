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
    Components.AppTextField {
        objectName: "cprParameter-" + row.parameter
        Layout.preferredWidth: 82
        Accessible.name: qsTrId("cpr." + row.parameter)
        validator: DoubleValidator { locale: "C"; decimals: 2; bottom: row.parameter === "angle" ? -360 : 0; top: 10000 }
        readonly property string modelText: Number(row.controller?.parameters[row.parameter] ?? 0).toFixed(row.parameter === "step" ? 2 : 1)
        function sync() { if (!activeFocus) text = modelText }
        Component.onCompleted: sync()
        onModelTextChanged: sync()
        onEditingFinished: {
            if (text.trim().length) row.controller?.setParameter(row.parameter, Number(text))
            text = modelText
        }
    }
}
