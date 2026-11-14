// Rendert das Darkfluenzer-App-Icon (pinke macOS-Kachel, großes weißes "C") als .iconset.
// Aufruf: swift make_icon.swift <ziel.iconset>
import AppKit

let args = CommandLine.arguments
guard args.count == 2 else {
    FileHandle.standardError.write("usage: make_icon.swift <out.iconset>\n".data(using: .utf8)!)
    exit(2)
}
let outDir = URL(fileURLWithPath: args[1])
try? FileManager.default.removeItem(at: outDir)
try! FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)

func render(px: Int) -> Data {
    let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px, bitsPerSample: 8,
        samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
        bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: px, height: px)
    NSGraphicsContext.saveGraphicsState()
    let ctx = NSGraphicsContext(bitmapImageRep: rep)!
    NSGraphicsContext.current = ctx
    ctx.imageInterpolation = .high
    let s = CGFloat(px) / 1024.0

    // Apple-Raster: 824-pt-Kachel auf 1024-pt-Fläche, Eckradius ~185 pt
    let tile = NSRect(x: 100 * s, y: 100 * s, width: 824 * s, height: 824 * s)
    let path = NSBezierPath(roundedRect: tile, xRadius: 185 * s, yRadius: 185 * s)

    NSGraphicsContext.saveGraphicsState()
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.30)
    shadow.shadowBlurRadius = 28 * s
    shadow.shadowOffset = NSSize(width: 0, height: -12 * s)
    shadow.set()
    NSColor(srgbRed: 0.93, green: 0.13, blue: 0.53, alpha: 1).setFill()
    path.fill()
    NSGraphicsContext.restoreGraphicsState()

    let gradient = NSGradient(colors: [
        NSColor(srgbRed: 1.00, green: 0.42, blue: 0.71, alpha: 1),  // oben: helles Pink
        NSColor(srgbRed: 0.86, green: 0.07, blue: 0.47, alpha: 1),  // unten: sattes Pink
    ])!
    gradient.draw(in: path, angle: -90)

    // dezenter Glanz oben
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    let gloss = NSGradient(colors: [
        NSColor.white.withAlphaComponent(0.18), NSColor.white.withAlphaComponent(0.0),
    ])!
    gloss.draw(in: NSRect(x: tile.minX, y: tile.midY, width: tile.width, height: tile.height / 2),
               angle: -90)
    NSGraphicsContext.restoreGraphicsState()

    // großes weißes "C" – SF Pro Rounded, Heavy
    var font = NSFont.systemFont(ofSize: 640 * s, weight: .heavy)
    if let rounded = font.fontDescriptor.withDesign(.rounded) {
        font = NSFont(descriptor: rounded, size: 640 * s) ?? font
    }
    let cg = ctx.cgContext
    cg.saveGState()
    cg.textMatrix = .identity
    cg.setShadow(offset: CGSize(width: 0, height: -8 * s), blur: 18 * s,
                 color: CGColor(srgbRed: 0.45, green: 0.0, blue: 0.22, alpha: 0.35))
    cg.setFillColor(CGColor(srgbRed: 1, green: 1, blue: 1, alpha: 1))
    let attrs: [NSAttributedString.Key: Any] = [
        .font: font,
        NSAttributedString.Key(kCTForegroundColorFromContextAttributeName as String): true,
    ]
    let line = CTLineCreateWithAttributedString(NSAttributedString(string: "C", attributes: attrs))
    // optisch zentrieren über die tatsächliche Glyphen-Bounding-Box
    let glyph = CTLineGetImageBounds(line, cg)
    cg.textPosition = CGPoint(x: tile.midX - glyph.width / 2 - glyph.minX,
                              y: tile.midY - glyph.height / 2 - glyph.minY)
    CTLineDraw(line, cg)
    cg.restoreGState()

    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let sizes: [(String, Int)] = [
    ("icon_16x16", 16), ("icon_16x16@2x", 32), ("icon_32x32", 32), ("icon_32x32@2x", 64),
    ("icon_128x128", 128), ("icon_128x128@2x", 256), ("icon_256x256", 256),
    ("icon_256x256@2x", 512), ("icon_512x512", 512), ("icon_512x512@2x", 1024),
]
for (name, px) in sizes {
    try! render(px: px).write(to: outDir.appendingPathComponent("\(name).png"))
}
print("iconset: \(outDir.path)")
