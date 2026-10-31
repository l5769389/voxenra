pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Layouts
import "../../../theme"

RowLayout {
    id: actions
    objectName: "cprBottomActions"
    required property var controller
    readonly property bool drawing: controller?.drawing ?? false
    readonly property bool editing: (controller?.pathEditing ?? false) || (controller?.finishing ?? false)
    readonly property bool hasPath: (controller?.selectedPathId ?? "") !== ""
    readonly property bool results: controller?.resultView ?? false
    readonly property bool canStart: (controller?.referencesReady ?? false) && !controller?.sourceMismatch
    spacing: 8

    component PathAction: ToolActionButton {
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        Layout.preferredHeight: 32
        iconSize: 20
    }
    PathAction {
        objectName: "cprNewPath"
        visible: !actions.drawing && !actions.editing && (actions.results || !actions.hasPath)
        iconName: "add"
        label: qsTrId("cpr.new")
        enabled: actions.canStart
        onClicked: actions.controller.startPath()
    }
    PathAction {
        objectName: "cprEditPath"
        visible: actions.hasPath && !actions.drawing && !actions.editing
        iconName: "cpr-path"
        label: qsTrId("cpr.edit")
        enabled: actions.canStart
        onClicked: actions.controller.setPathEditing(true)
    }
    PathAction {
        objectName: "cprReferenceBrowse"
        visible: actions.hasPath && !actions.drawing && !actions.editing
        iconName: actions.results ? "layout-quad" : "layout-columns"
        label: qsTrId(actions.results ? "cpr.referenceBrowse" : "cpr.showResults")
        enabled: actions.canStart
        onClicked: actions.controller.setReferenceBrowsing(actions.results)
    }
    PathAction {
        objectName: "cprFinishPath"
        visible: actions.drawing || actions.editing
        iconName: "check"
        label: qsTrId("cpr.done")
        tooltipText: qsTrId("cpr.finishHint")
        enabled: actions.controller?.canFinishEditing ?? false
        normalColor: Theme.primaryButtonBackground
        hoverColor: Theme.primaryButtonHover
        pressedColor: Theme.primaryButtonPressed
        disabledColor: Theme.primaryButtonDisabled
        actionRole: "primary"
        onClicked: actions.controller.finishEditing()
    }
    PathAction {
        objectName: "cprCancelPath"
        visible: actions.drawing
        iconName: "close"
        label: qsTrId("cpr.cancel")
        tooltipText: label + " (Esc)"
        onClicked: actions.controller.cancel_operation()
    }
}
