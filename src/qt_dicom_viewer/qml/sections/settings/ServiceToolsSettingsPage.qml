pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../../theme"

ColumnLayout {
    id: root
    required property var settingsController
    readonly property var values: settingsController.values.services
    property bool advancedMtfExpanded: false
    spacing: 12
    SettingsSection {
        sectionKey: "services-mtf"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: "MTF"
        description: qsTrId("mtf.settingsHelp")
        Components.AppCheckBox {
            objectName: "setting-services-mtfGaussianEquivalent"
            text: qsTrId("mtf.equivalentSetting")
            checked: root.values.mtfGaussianEquivalent
            onClicked: root.settingsController.setValue("services", "mtfGaussianEquivalent", checked)
        }
        Text {
            objectName: "mtfEquivalentSettingHelp"
            Layout.fillWidth: true
            text: qsTrId("mtf.equivalentSettingHelp")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
        Text {
            text: qsTrId("mtf.frequencyUnit")
            color: Theme.textSecondary
            font.pixelSize: 12
        }
        Components.AppComboBox {
            objectName: "setting-services-mtfFrequencyUnit"
            Layout.fillWidth: true
            Layout.maximumWidth: 220
            Accessible.name: qsTrId("mtf.frequencyUnit")
            model: ["lp/mm", "lp/cm"]
            currentIndex: root.values.mtfFrequencyUnit === "lp/cm" ? 1 : 0
            onActivated: index => root.settingsController.setValue("services", "mtfFrequencyUnit", model[index])
        }
        Components.AppButton {
            objectName: "mtfAdvancedSettings"
            Layout.fillWidth: true
            text: qsTrId("mtf.advanced")
            iconName: root.advancedMtfExpanded ? "chevron-up" : "chevron-down"
            checked: root.advancedMtfExpanded
            onClicked: root.advancedMtfExpanded = !root.advancedMtfExpanded
        }
        SettingSlider {
            visible: root.advancedMtfExpanded
            Layout.fillWidth: true
            settingName: "services-mtfSensitivityPercent"
            title: qsTrId("mtf.sensitivitySetting")
            value: root.values.mtfSensitivityPercent
            from: 1; to: 100; stepSize: 1; suffix: "%"
            onEdited: value => root.settingsController.setValue("services", "mtfSensitivityPercent", value)
        }
        Text {
            objectName: "mtfSensitivitySettingHelp"
            visible: root.advancedMtfExpanded
            Layout.fillWidth: true
            text: qsTrId("mtf.sensitivitySettingHelp")
            color: Theme.textMuted
            font.pixelSize: 11
            wrapMode: Text.Wrap
        }
    }
    SettingsSection {
        sectionKey: "services-fwhm"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: "FWHM · " + qsTrId("ramp.conversion")
        description: qsTrId("ramp.conversionHelp")
        Components.AppComboBox {
            objectName: "setting-services-rampThicknessAngle"
            Layout.fillWidth: true
            Layout.maximumWidth: 260
            Accessible.name: qsTrId("ramp.conversion")
            model: [qsTrId("ramp.angle23"), qsTrId("ramp.angle45")]
            currentIndex: root.values.rampThicknessAngle === 45 ? 1 : 0
            onActivated: index => root.settingsController.setValue("services", "rampThicknessAngle", index === 1 ? 45 : 23)
        }
    }
}
