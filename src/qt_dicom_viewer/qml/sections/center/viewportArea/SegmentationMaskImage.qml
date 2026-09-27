import QtQuick

// Keep the displayed texture intact while the next preview is decoded. Only
// swap the two layers when the requested image is ready; never fade masks.
Item {
    id: root
    property url source
    property int front: 0
    property bool initialized: false
    readonly property bool maskReady: (front === 0 ? first.status : second.status) === Image.Ready

    function stage() {
        if (!initialized) return
        if (!source.toString()) {
            first.source = ""
            second.source = ""
            return
        }
        const current = front === 0 ? first : second
        if (current.source.toString() === source.toString() && current.status === Image.Ready) return
        const next = front === 0 ? second : first
        next.source = source
        swapIfReady(next)
    }
    function swapIfReady(next) {
        if (next.status === Image.Ready && next.source.toString() === source.toString())
            front = next === first ? 0 : 1
    }
    onSourceChanged: stage()
    Component.onCompleted: { initialized = true; stage() }
    Image {
        id: first
        anchors.fill: parent
        visible: root.front === 0
        asynchronous: false
        retainWhileLoading: true
        smooth: false
        cache: false
        onStatusChanged: root.swapIfReady(first)
    }
    Image {
        id: second
        anchors.fill: parent
        visible: root.front === 1
        asynchronous: false
        retainWhileLoading: true
        smooth: false
        cache: false
        onStatusChanged: root.swapIfReady(second)
    }
}
