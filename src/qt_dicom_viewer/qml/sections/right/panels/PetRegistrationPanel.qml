pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "petRegistrationPanel"
    required property var controller
    spacing: 12
    readonly property string parameterContext: JSON.stringify([controller?.registrationParameters ?? [],
        controller?.registrationActive ?? false, controller?.ready ?? false])
    onParameterContextChanged: discardDraft()
    function discardDraft() {
        for (let i = 0; i < parameters.count; ++i) parameters.itemAt(i)?.input.sync()
    }
    function applyDraft() {
        if (!panel.controller?.ready || !panel.controller.registrationActive) return
        const values = Array(6)
        for (let i = 0; i < parameters.count; ++i) {
            const row = parameters.itemAt(i), input = row.input
            if (!input.acceptableInput || !input.text.trim() || !Number.isFinite(Number(input.text))) return
            values[row.modelData.parameter] = Number(input.text)
        }
        panel.controller.setRegistrationParameters(values)
        discardDraft()
    }
    onControllerChanged: discardDraft()
    onVisibleChanged: if (!visible) discardDraft()
    Components.PanelHeading {
        objectName: "PetRegistrationPanelHeading"
        title: qsTrId("text.1054")
        explanation: qsTrId("text.1058")
    }
    Text {
        Layout.fillWidth: true
        text: qsTrId("text.1055")
        color: Theme.textMuted
        wrapMode: Text.Wrap
        font.pixelSize: 12
    }
        Text {
            Layout.fillWidth: true
            visible: panel.controller.registrationStatus !== ""
            text: panel.controller.registrationStatus
            color: Theme.textPrimary
            wrapMode: Text.Wrap
        }
        Components.AppButton {
            objectName: "togglePetRegistration"
            Layout.fillWidth: true
            enabled: panel.controller.ready
            text: panel.controller.registrationActive ? qsTrId("text.1056") : qsTrId("text.1057")
            onClicked: panel.controller.setRegistrationActive(!panel.controller.registrationActive)
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            enabled: panel.controller.ready && panel.controller.registrationActive
            Repeater {
                id: parameters
                model: [
                    {label: qsTrId("text.1059"), parameter: 0}, {label: qsTrId("text.1060"), parameter: 3},
                    {label: qsTrId("text.1061"), parameter: 1}, {label: qsTrId("text.1062"), parameter: 4},
                    {label: qsTrId("text.1063"), parameter: 2}, {label: qsTrId("text.1064"), parameter: 5}
                ]
                delegate: ColumnLayout {
                    id: parameterRow
                    required property var modelData
                    readonly property alias input: parameterInput
                    Layout.fillWidth: true
                    Text { text: parameterRow.modelData.label; color: Theme.textMuted; font.pixelSize: 11 }
                    Components.AppNumberField {
                        id: parameterInput
                        editContext: [panel.controller, panel.controller?.registrationActive ?? false]
                        commitOnFinish: false
                        objectName: "registrationParameter-" + parameterRow.modelData.parameter
                        Layout.fillWidth: true
                        color: Theme.textPrimary
                        numberValue: panel.controller.registrationParameters[parameterRow.modelData.parameter]
                        minimum: -10000
                        maximum: 10000
                        decimals: 2
                        onAccepted: panel.applyDraft()
                        Keys.onEscapePressed: panel.discardDraft()
                    }
                }
            }
        }
        Text {
            Layout.fillWidth: true
            text: qsTrId("numeric.applyHint")
            color: Theme.textMuted; font.pixelSize: 11; wrapMode: Text.Wrap
        }
        Components.AppButton {
            objectName: "applyRegistrationParameters"
            Layout.fillWidth: true
            text: qsTrId("text.1090")
            enabled: panel.controller?.ready === true && panel.controller.registrationActive
            onClicked: panel.applyDraft()
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton { Layout.fillWidth: true; text: qsTrId("text.1065"); enabled: panel.controller.ready; onClicked: panel.controller.centerAlign() }
            Components.AppButton { Layout.fillWidth: true; text: qsTrId("text.0282"); enabled: panel.controller.ready; onClicked: panel.controller.resetRegistration() }
        }
        RowLayout {
            Layout.fillWidth: true
            Components.AppButton { Layout.fillWidth: true; text: qsTrId("text.1066"); enabled: panel.controller.ready; onClicked: panel.controller.loadRegistration() }
            Components.AppButton { Layout.fillWidth: true; text: qsTrId("text.1067"); enabled: panel.controller.ready; onClicked: panel.controller.saveRegistration() }
        }


}
