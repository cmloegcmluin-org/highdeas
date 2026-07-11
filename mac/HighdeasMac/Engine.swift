import Foundation

/// Launches and addresses the Python engine — the same Flask app the PC runs,
/// in serve-only mode (no pywebview, no browser tab), on a port this shell
/// chooses. The engine keeps all of its own behaviors: the shared folder
/// store, the ingest scanner, the LAN upload listener, and the self-update
/// (whose re-exec keeps the pid, so the child handle stays valid).
enum Engine {
    /// Where the Highdeas checkout lives. An Info.plist override first (the
    /// build stamps it), then the conventional home.
    static var repo: URL {
        if let configured = Bundle.main.object(forInfoDictionaryKey: "HighdeasRepo") as? String,
           !configured.isEmpty {
            return URL(fileURLWithPath: (configured as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appending(path: "workspace/highdeas")
    }

    /// A free loopback port, asked of the kernel the honest way.
    static func pickPort() -> Int {
        let sock = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(sock) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(sock, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else { return 5099 }
        var out = sockaddr_in()
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        withUnsafeMutablePointer(to: &out) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                _ = getsockname(sock, $0, &len)
            }
        }
        return Int(UInt16(bigEndian: out.sin_port))
    }

    static func launch(port: Int) throws -> Process {
        let python = repo.appending(path: ".venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            throw NSError(domain: "Highdeas", code: 1, userInfo: [
                NSLocalizedDescriptionKey:
                    "No venv at \(repo.path)/.venv — see the README's Mac setup."])
        }
        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "highdeas.app"]
        process.currentDirectoryURL = repo
        var environment = ProcessInfo.processInfo.environment
        environment["HIGHDEAS_DESKTOP"] = "0"       // serve-only: this shell is the window
        environment["HIGHDEAS_OPEN_BROWSER"] = "0"
        environment["HIGHDEAS_PORT"] = String(port)
        process.environment = environment
        try process.run()
        return process
    }
}

/// The same warming-up card the pages use, in the app's own system colors.
enum Splash {
    static let html = """
    <!doctype html>
    <html lang="en"><head><meta charset="utf-8"><style>
      :root { color-scheme: light dark; }
      html, body { height: 100%; margin: 0; }
      body { display: flex; align-items: center; justify-content: center;
             background: Canvas; color: CanvasText;
             font-family: -apple-system, system-ui, sans-serif; }
      .box { text-align: center; }
      .name { font-size: 1.9rem; font-weight: 650; letter-spacing: .01em; }
      .sub { margin-top: .55rem; font-size: .85rem; opacity: .6; }
      .spin { width: 34px; height: 34px; margin: 1.5rem auto 0; border-radius: 50%;
              border: 3px solid color-mix(in srgb, CanvasText 25%, transparent);
              border-top-color: #22c55e;
              animation: spin .8s linear infinite; }
      @keyframes spin { to { transform: rotate(360deg); } }
    </style></head>
    <body><div class="box">
      <div class="name">Highdeas</div>
      <div class="spin"></div>
      <div class="sub">Loading…</div>
    </div></body></html>
    """
}
