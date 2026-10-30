pragma ComponentBehavior: Bound
import QtQuick

// Fast requests complete without flashing a loading message or spinner.
// This only controls feedback; callers keep their actual busy/input guards.
QtObject {
    id: root
    property bool active: false
    property var activityKey: null
    property int delayMs: 300
    readonly property bool showing: active && elapsed
    property bool elapsed: false

    function restart() {
        timer.stop()
        elapsed = false
        if (active) timer.start()
    }
    onActiveChanged: restart()
    onActivityKeyChanged: restart()
    Component.onCompleted: restart()
    property Timer timer: Timer {
        interval: root.delayMs
        onTriggered: root.elapsed = root.active
    }
}
