pragma Singleton
import QtQuick
QtObject {
    function format(template, values) {
        return template.replace(/\{([a-zA-Z_][a-zA-Z_0-9]*)\}/g, (match, key) =>
            values[key] === undefined ? match : String(values[key]))
    }
}
