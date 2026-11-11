pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../components" as Components
import "../center/viewportArea/measurementLayer" as Measurement
import "../../theme"
SettingsSplit {
    id: root
    required property var settingsController
    SettingsSection {
        sectionKey: "roi-metrics"
        settingsController: root.settingsController
        Layout.fillWidth: true
        title: qsTrId("text.0852")
        description: qsTrId("text.0853")
        GridLayout {
            Layout.fillWidth: true
            columns: width > 340 ? 2 : 1
            columnSpacing: 16; rowSpacing: 2
            Repeater {
                model: root.settingsController.roiFields
                delegate: Components.AppCheckBox {
                    required property var modelData
                    objectName: "setting-roi-" + modelData.key
                    Layout.fillWidth: true
                    text: modelData.label
                    checked: root.settingsController.values.roi[modelData.key]
                    onClicked: root.settingsController.setValue("roi", modelData.key, checked)
                }
            }
        }
    }
    preview: Component {
        ColumnLayout {
            spacing: 10
            Text { text: qsTrId("text.0854"); color: Theme.textMuted; font.pixelSize: 12 }
            Measurement.RoiMetricCard {
                settingsController: root.settingsController
                Layout.fillWidth: true
                accentColor: root.settingsController.values.measurement.completedColor
                visibleMetrics: root.settingsController.values.roi
                metricFontSize: root.settingsController.values.measurement.fontSize
                measurement: ({type: "rect", label: qsTrId("text.0375"), metrics: {area_mm2: 400, width_mm: 20, height_mm: 20, mean: 40, std: 8.5, minimum: 12, maximum: 65, pixel_count: 400, unit: "HU"}})
            }
        }
    }
}
