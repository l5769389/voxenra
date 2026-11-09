.pragma library

// Screen-space fallback only: never overwrite a user's saved image-space anchor.
function place(preferred, labelWidth, labelHeight, viewportWidth, viewportHeight, reserved, softObstacles, preservePreferred) {
    const margin = 8, gap = 6
    const clamp = p => ({x: Math.max(margin, Math.min(viewportWidth - labelWidth - margin, p.x)),
                         y: Math.max(margin, Math.min(viewportHeight - labelHeight - margin, p.y))})
    const origin = clamp(preferred)
    const obstacles = reserved || []
    const soft = softObstacles || []
    const overlap = (p, regions) => regions.reduce((sum, r) => sum
        + Math.max(0, Math.min(p.x + labelWidth + gap, r.x + r.width) - Math.max(p.x - gap, r.x))
        * Math.max(0, Math.min(p.y + labelHeight + gap, r.y + r.height) - Math.max(p.y - gap, r.y)), 0)
    if (overlap(origin, obstacles) === 0 && (preservePreferred || overlap(origin, soft) === 0)) return origin
    const candidates = [origin]
    // Metadata occupies viewport edges; examine each free boundary as well as
    // the centre. A bounded candidate set avoids a pixel-by-pixel layout search.
    for (const r of obstacles.concat(soft)) {
        candidates.push(clamp({x: origin.x, y: r.y + r.height + gap}),
                        clamp({x: origin.x, y: r.y - labelHeight - gap}),
                        clamp({x: r.x + r.width + gap, y: origin.y}),
                        clamp({x: r.x - labelWidth - gap, y: origin.y}))
    }
    candidates.push(clamp({x: (viewportWidth-labelWidth)/2, y: (viewportHeight-labelHeight)/2}))
    let best = origin, bestOverlap = Infinity, bestSoftOverlap = Infinity, bestDistance = Infinity
    for (const p of candidates) {
        const area = overlap(p, obstacles)
        const softArea = overlap(p, soft)
        const distance = Math.pow(p.x-origin.x, 2) + Math.pow(p.y-origin.y, 2)
        if (area < bestOverlap || (area === bestOverlap && (softArea < bestSoftOverlap
                || (softArea === bestSoftOverlap && distance < bestDistance)))) {
            best = p; bestOverlap = area; bestSoftOverlap = softArea; bestDistance = distance
        }
    }
    return best
}
