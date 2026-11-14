// Darkfluenzer.app – dünner macOS-Starter mit pinkem „C“ (PHASENPLAN_FRONT_V1 F0/F4).
//
// Die App enthält KEINE eigene Prozesslogik und keine zweite Bedienoberfläche. Sie ruft
// ausschließlich <projekt>/local/.venv/bin/python -m darkfluenzer up|down|comfy start --json
// auf (backend/src/darkfluenzer/runtime.py) und öffnet das Cockpit erst nach dessen
// Health-Check. Der Projektordner steht als DFProjectRoot in Info.plist (launcher/install.sh).
import AppKit

struct CLIResult {
    let exitCode: Int32
    let json: [String: Any]?
    let stdout: String
    let stderr: String
    var ok: Bool { exitCode == 0 && (json?["ok"] as? Bool ?? false) }
    var error: String { json?["error"] as? String ?? "internal" }
    var message: String {
        if let m = json?["message"] as? String { return m }
        let raw = (stderr.isEmpty ? stdout : stderr).trimmingCharacters(in: .whitespacesAndNewlines)
        return raw.isEmpty ? "Unbekannter Fehler (Exit-Code \(exitCode))." : raw
    }
}

final class AppController: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSWindow!
    private let titleLabel = NSTextField(labelWithString: "Darkfluenzer")
    private let stateLabel = NSTextField(labelWithString: "Prüfe Status …")
    private let detailLabel = NSTextField(wrappingLabelWithString: "")
    private let spinner = NSProgressIndicator()
    private let openButton = NSButton(title: "Cockpit öffnen", target: nil, action: nil)
    private let stopButton = NSButton(title: "Stoppen", target: nil, action: nil)
    private let logButton = NSButton(title: "Logs", target: nil, action: nil)
    private var busy = false

    private lazy var projectRoot: URL? = {
        guard let raw = Bundle.main.object(forInfoDictionaryKey: "DFProjectRoot") as? String,
              !raw.isEmpty else { return nil }
        return URL(fileURLWithPath: raw, isDirectory: true)
    }()
    private var python: URL? { projectRoot?.appendingPathComponent("local/.venv/bin/python") }
    private var logsDir: URL? { projectRoot?.appendingPathComponent("local/logs", isDirectory: true) }

    // MARK: Lebenszyklus

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildMenu()
        buildWindow()
        appLog("App gestartet (pid \(ProcessInfo.processInfo.processIdentifier))")
        ensureRunning()
    }

    /// Zweiter Doppelklick/Dock-Klick bei laufender App: idempotent prüfen und öffnen.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil)
        appLog("Reopen angefordert")
        ensureRunning()
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationDockMenu(_ sender: NSApplication) -> NSMenu? {
        let menu = NSMenu()
        menu.addItem(withTitle: "Cockpit öffnen", action: #selector(openClicked), keyEquivalent: "")
        menu.addItem(withTitle: "Stoppen", action: #selector(stopClicked), keyEquivalent: "")
        return menu
    }

    // MARK: Aktionen

    @objc private func openClicked() { ensureRunning() }
    @objc private func logsClicked() {
        if let dir = logsDir { NSWorkspace.shared.open(dir) }
    }

    /// Cockpit-Server bereitstellen, nach erfolgreichem Health-Check öffnen, dann ComfyUI starten.
    private func ensureRunning() {
        guard !busy else { return }
        setBusy("Cockpit wird gestartet bzw. geprüft …")
        runCLI(["up"]) { [weak self] r in
            guard let self else { return }
            self.appLog("up -> exit=\(r.exitCode) \(r.json?["result"] ?? r.error)")
            guard r.ok, let s = r.json?["url"] as? String, let url = URL(string: s) else {
                self.busy = false
                self.showStopped("Cockpit nicht gestartet")
                self.failure("Cockpit konnte nicht gestartet werden", r)
                return
            }
            self.appLog("Browser öffnen: \(url.absoluteString)")
            NSWorkspace.shared.open(url)
            self.stateLabel.stringValue = "● Cockpit läuft"
            self.stateLabel.textColor = .systemGreen
            self.detailLabel.stringValue = "\(s)\nComfyUI wird gestartet bzw. geprüft …"
            self.startComfy(cockpit: s)
        }
    }

    private func startComfy(cockpit: String) {
        runCLI(["comfy", "start"]) { [weak self] r in
            guard let self else { return }
            self.busy = false
            self.idle()
            self.appLog("comfy start -> exit=\(r.exitCode) \(r.json?["result"] ?? r.error)")
            let comfy: String
            if r.ok {
                comfy = "ComfyUI bereit."
            } else if r.error == "foreign_instance" {
                comfy = "ComfyUI: fremde Instanz – wird weder übernommen noch beendet."
            } else {
                comfy = "ComfyUI-Start fehlgeschlagen (Details im Cockpit und in den Logs)."
                self.failure("ComfyUI konnte nicht gestartet werden", r)
            }
            self.detailLabel.stringValue = "\(cockpit)\n\(comfy)\nFenster schließen beendet nichts."
            self.openButton.isEnabled = true
            self.stopButton.isEnabled = true
        }
    }

    @objc private func stopClicked() {
        guard !busy else { return }
        setBusy("Cockpit und ComfyUI werden gestoppt …")
        runCLI(["down"]) { [weak self] r in
            guard let self else { return }
            self.busy = false
            self.appLog("down -> exit=\(r.exitCode) \(r.json?["result"] ?? r.error) comfyui=\(r.json?["comfyui"] ?? "-")")
            guard r.ok else {
                self.showStopped("Status unbekannt")
                self.failure("Stoppen fehlgeschlagen", r)
                return
            }
            self.showStopped("Gestoppt")
            if r.json?["comfyui"] as? String == "not_managed" {
                self.detailLabel.stringValue = "Fremde ComfyUI-Instanz läuft weiter (nicht von Darkfluenzer gestartet)."
            }
        }
    }

    /// Fehlgeschlagene Schritte nie als Erfolg zeigen: Meldung mit letzten Logzeilen.
    private func failure(_ title: String, _ r: CLIResult) {
        var text = r.message
        if let tail = (r.json?["details"] as? [String: Any])?["log_tail"] as? String, !tail.isEmpty {
            text += "\n\nLetzte Logzeilen:\n" + tail.split(separator: "\n").suffix(8).joined(separator: "\n")
        }
        if alert(title, text, buttons: ["Logs öffnen", "Schließen"]) == .alertFirstButtonReturn {
            logsClicked()
        }
    }

    // MARK: CLI-Brücke (einzige Verbindung zur Prozesslogik)

    private func runCLI(_ args: [String], completion: @escaping (CLIResult) -> Void) {
        guard let root = projectRoot, let py = python else {
            completion(CLIResult(exitCode: 2, json: nil, stdout: "",
                                 stderr: "DFProjectRoot fehlt in Info.plist. App mit launcher/install.sh neu installieren."))
            return
        }
        guard FileManager.default.isExecutableFile(atPath: py.path) else {
            completion(CLIResult(exitCode: 2, json: nil, stdout: "",
                                 stderr: "Darkfluenzer-Python fehlt: \(py.path)\nBitte launcher/install.sh ausführen."))
            return
        }
        DispatchQueue.global(qos: .userInitiated).async {
            let p = Process()
            p.executableURL = py
            p.arguments = ["-m", "darkfluenzer"] + args + ["--json"]
            p.currentDirectoryURL = root
            var env = ProcessInfo.processInfo.environment
            env["DARKFLUENZER_ROOT"] = root.path
            p.environment = env
            let out = Pipe(), err = Pipe()
            p.standardOutput = out
            p.standardError = err
            p.standardInput = FileHandle.nullDevice
            var result: CLIResult
            do {
                try p.run()
                // Beide Pipes parallel leeren, damit keine volle Pipe den Prozess blockiert.
                var errData = Data()
                let errReader = DispatchQueue(label: "stderr")
                let group = DispatchGroup()
                group.enter()
                errReader.async { errData = err.fileHandleForReading.readDataToEndOfFile(); group.leave() }
                let outData = out.fileHandleForReading.readDataToEndOfFile()
                group.wait()
                p.waitUntilExit()
                let stdout = String(decoding: outData, as: UTF8.self)
                let lastLine = stdout.split(separator: "\n").last.map(String.init) ?? ""
                let json = (try? JSONSerialization.jsonObject(with: Data(lastLine.utf8))) as? [String: Any]
                result = CLIResult(exitCode: p.terminationStatus, json: json, stdout: stdout,
                                   stderr: String(decoding: errData, as: UTF8.self))
            } catch {
                result = CLIResult(exitCode: 1, json: nil, stdout: "",
                                   stderr: "Darkfluenzer-CLI nicht ausführbar: \(error.localizedDescription)")
            }
            DispatchQueue.main.async { completion(result) }
        }
    }

    // MARK: Darstellung

    private func setBusy(_ text: String) {
        busy = true
        stateLabel.stringValue = text
        stateLabel.textColor = .secondaryLabelColor
        spinner.isHidden = false
        spinner.startAnimation(nil)
        [openButton, stopButton].forEach { $0.isEnabled = false }
    }

    private func idle() {
        spinner.stopAnimation(nil)
        spinner.isHidden = true
    }

    private func showStopped(_ text: String) {
        idle()
        stateLabel.stringValue = "○ " + text
        stateLabel.textColor = .secondaryLabelColor
        detailLabel.stringValue = "Cockpit-Server und eigene ComfyUI sind nicht aktiv."
        openButton.isEnabled = true
        stopButton.isEnabled = false
    }

    @discardableResult
    private func alert(_ title: String, _ text: String, buttons: [String] = ["OK"]) -> NSApplication.ModalResponse {
        appLog("Dialog: \(title) – \(text.replacingOccurrences(of: "\n", with: " ⏎ "))")
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.alertStyle = .warning
        buttons.forEach { a.addButton(withTitle: $0) }
        NSApp.activate(ignoringOtherApps: true)
        return a.runModal()
    }

    private func appLog(_ line: String) {
        guard let dir = logsDir else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("app.log")
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let data = Data("\(f.string(from: Date())) \(line)\n".utf8)
        if let h = try? FileHandle(forWritingTo: url) {
            h.seekToEndOfFile(); h.write(data); try? h.close()
        } else {
            try? data.write(to: url)
        }
    }

    // MARK: Aufbau

    private func buildMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Über Darkfluenzer",
                        action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Darkfluenzer beenden", action: #selector(NSApplication.terminate(_:)),
                        keyEquivalent: "q")
        appItem.submenu = appMenu
        let winItem = NSMenuItem()
        main.addItem(winItem)
        let winMenu = NSMenu(title: "Fenster")
        winMenu.addItem(withTitle: "Schließen", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        winItem.submenu = winMenu
        NSApp.mainMenu = main
    }

    private func buildWindow() {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 440, height: 230),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Darkfluenzer"
        window.isReleasedWhenClosed = false
        window.delegate = self

        let icon = NSImageView(image: NSApp.applicationIconImage)
        icon.imageScaling = .scaleProportionallyUpOrDown
        titleLabel.font = .systemFont(ofSize: 20, weight: .semibold)
        stateLabel.font = .systemFont(ofSize: 13, weight: .medium)
        detailLabel.font = .systemFont(ofSize: 11)
        detailLabel.textColor = .secondaryLabelColor
        detailLabel.preferredMaxLayoutWidth = 300
        spinner.style = .spinning
        spinner.controlSize = .small
        spinner.isHidden = true

        for (b, sel) in [(openButton, #selector(openClicked)), (stopButton, #selector(stopClicked)),
                         (logButton, #selector(logsClicked))] {
            b.target = self
            b.action = sel
            b.bezelStyle = .rounded
        }
        openButton.keyEquivalent = "\r"
        [openButton, stopButton].forEach { $0.isEnabled = false }

        let stateRow = NSStackView(views: [spinner, stateLabel])
        stateRow.spacing = 6
        let text = NSStackView(views: [titleLabel, stateRow, detailLabel])
        text.orientation = .vertical
        text.alignment = .leading
        text.spacing = 6
        let top = NSStackView(views: [icon, text])
        top.alignment = .top
        top.spacing = 16
        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let buttons = NSStackView(views: [logButton, spacer, stopButton, openButton])
        buttons.spacing = 8
        let root = NSStackView(views: [top, buttons])
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 18
        root.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)
        root.translatesAutoresizingMaskIntoConstraints = false

        let content = NSView()
        content.addSubview(root)
        NSLayoutConstraint.activate([
            icon.widthAnchor.constraint(equalToConstant: 72),
            icon.heightAnchor.constraint(equalToConstant: 72),
            root.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            root.topAnchor.constraint(equalTo: content.topAnchor),
            root.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            buttons.widthAnchor.constraint(equalTo: root.widthAnchor, constant: -40),
        ])
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
}

let app = NSApplication.shared
let controller = AppController()
app.delegate = controller
app.setActivationPolicy(.regular)
app.run()
