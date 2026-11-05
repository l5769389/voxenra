.pragma library

// A rebuilt row can hand focus back to its Loader. Keep the scroll position
// until a control in the tab chain actually receives focus.
function revealFocused(view, item) {
    if (item?.activeFocusOnTab) reveal(view, item)
}

function reveal(view, item) {
    if (!item) return
    let ancestor = item
    while (ancestor && ancestor !== view.contentItem) ancestor = ancestor.parent
    if (!ancestor) return
    const top = item.mapToItem(view.contentItem, 0, 0).y
    const bottom = top + Math.min(item.height, view.height)
    const target = top < view.contentY ? top : Math.max(view.contentY, bottom - view.height)
    view.contentY = Math.max(view.originY, Math.min(target, view.originY + Math.max(0, view.contentHeight - view.height)))
}
