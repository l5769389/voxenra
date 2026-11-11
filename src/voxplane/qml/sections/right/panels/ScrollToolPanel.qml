pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../components" as Components
import "../../../components/ShortcutCaption.js" as KeysText
import "../../../theme"

ColumnLayout {
    id: panel
    objectName: "scrollToolPanel"
    required property var viewportController
    readonly property int count: viewportController?.sliceCount ?? 0
    readonly property int current: viewportController?.sliceIndex ?? -1
    readonly property var shortcuts: typeof appController !== "undefined" ? appController.shortcutController?.bindings ?? [] : []
    spacing: 8
    Text {
        Layout.fillWidth: true
        text: panel.count > 0 ? I18n.format(qsTrId("browse.page"), {page: panel.current + 1, total: panel.count}) : qsTrId("text.1026")
        color: Theme.textSecondary
        font.pixelSize: 12
        wrapMode: Text.Wrap
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 6; rowSpacing: 6
        uniformCellWidths: true
        Repeater {
            model: [{key:"prev",label:qsTrId("input.previousSlice"),action:"scroll-prev",start:true},
                    {key:"next",label:qsTrId("input.nextSlice"),action:"scroll-next",start:false},
                    {key:"first",action:"scroll-first",label:qsTrId("text.1027"),start:true}, {key:"last",action:"scroll-last",label:qsTrId("text.1028"),start:false},
                    {key:"back10",label:qsTrId("text.1029"),start:true}, {key:"forward10",label:qsTrId("text.1030"),start:false}]
            delegate: Components.AppButton {
                required property var modelData
                objectName: "scrollShortcut-" + modelData.key
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                compact: true
                shortcutTitle: modelData.label
                captionKey: KeysText.hint(modelData.action, panel.shortcuts)
                enabled: panel.count > 1 && panel.current >= 0
                    && (modelData.start ? panel.current > 0 : panel.current < panel.count - 1)
                onClicked: {
                    const targets = {prev:panel.current - 1, next:panel.current + 1,
                        first:0, last:panel.count - 1, back10:panel.current - 10, forward10:panel.current + 10}
                    panel.viewportController.setSliceIndex(targets[modelData.key])
                }
            }
        }
    }
}
