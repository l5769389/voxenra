import QtQuick
AppTextField {
    id: field
    required property real numberValue
    property real minimum: 0
    property real maximum: 100
    property int decimals: 2
    property bool publishing: false
    // A grouped form disables automatic commits and submits its fields together.
    property bool commitOnFinish: true
    property var editContext: null
    property var contextSnapshot: null
    signal edited(real value)
    function modelText() { return Number.isFinite(numberValue) ? String(Number(numberValue.toFixed(decimals))) : "" }
    function sync() { text = modelText() }
    function contextMatches(left, right) {
        if (left === right) return true
        if (!Array.isArray(left) || !Array.isArray(right) || left.length !== right.length) return false
        for (let i = 0; i < left.length; ++i)
            if (left[i] !== right[i]) return false
        return true
    }
    function syncContext() {
        if (!contextMatches(editContext, contextSnapshot)) sync()
        contextSnapshot = Array.isArray(editContext) ? editContext.slice() : editContext
    }
    Component.onCompleted: { sync(); syncContext() }
    onNumberValueChanged: if (!publishing) sync()
    onEditContextChanged: syncContext()
    onEnabledChanged: if (!enabled) sync()
    onVisibleChanged: if (!visible) sync()
    Accessible.description: qsTrId(commitOnFinish ? "numeric.commitHint" : "numeric.applyHint")
    AppToolTip { visible: field.hovered; text: field.Accessible.description }
    validator: DoubleValidator { locale: "C"; bottom: field.minimum; top: field.maximum; decimals: field.decimals; notation: DoubleValidator.StandardNotation }
    function commit() {
        // Qt can emit editingFinished before enabledChanged during disabling.
        if (!enabled || !visible) { sync(); return }
        if (!commitOnFinish) return
        if (text !== modelText() && acceptableInput && text.trim() && Number.isFinite(Number(text))) {
            publishing = true
            edited(Number(text))
            publishing = false
        }
        sync()
    }
    onAccepted: commit()
    onEditingFinished: commit()
    onActiveFocusChanged: if (!activeFocus) commit()
    Keys.onEscapePressed: event => { sync(); event.accepted = true }
}
