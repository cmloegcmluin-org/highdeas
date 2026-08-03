import AppKit
import WebKit

/// Owns the one window and the Python engine underneath it.
///
/// Lifecycle: launch → engine starts (serve-only Flask on a local port) →
/// splash in the WKWebView until the port answers → the inbox loads. The
/// engine self-updates (pull + re-exec, same pid, same port), which drops
/// connections for a moment — the navigation delegate treats any load
/// failure as "engine is between lives" and quietly returns to the splash
/// until the port answers again. Closing the window quits; quitting stops
/// the engine.
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var engine: Process?
    /// How many engines this shell has started, so a crash loop stops rather
    /// than spinning forever.
    private var engineStarts = 0
    private let port = Engine.pickPort()

    func applicationDidFinishLaunching(_ notification: Notification) {
        webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        webView.navigationDelegate = self
        webView.loadHTMLString(Splash.html, baseURL: nil)

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1360, height: 900),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        window.title = "Highdeas"
        window.contentView = webView
        window.delegate = self
        // The system remembers where the window lives — position, size,
        // screen — with none of the hand-rolled tracking the script era needed.
        window.setFrameAutosaveName("HighdeasMain")
        if !window.setFrameUsingName("HighdeasMain") {
            window.center()
        }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        do {
            try startEngine()
        } catch {
            present(error: "The Highdeas engine could not start: \(error.localizedDescription)")
            return
        }
        waitForEngineThenLoad()
    }

    /// Start an engine and arrange to hear about it dying.
    ///
    /// A self-update does not come through here: its re-exec keeps the pid, so
    /// the process this handle watches never terminates. What does come through
    /// is an engine that actually went — a re-exec that failed, a crash, a kill
    /// — and until this existed nothing noticed. The shell only knocked on the
    /// port while a page was failing to load, so an engine that died under a
    /// page already on screen left a window that looked fine and answered
    /// nothing, with no path back short of quitting the app.
    private func startEngine() throws {
        engineStarts += 1
        let process = try Engine.launch(port: port)
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async { self?.engineDied() }
        }
        engine = process
    }

    private func engineDied() {
        guard engineStarts < Self.engineAttempts else {
            present(error: "The Highdeas engine keeps exiting. "
                    + "Try running it by hand to see why:\n\n"
                    + "\(Engine.repo.path)/.venv/bin/python -m highdeas.app")
            return
        }
        webView.loadHTMLString(Splash.html, baseURL: nil)
        do {
            try startEngine()
        } catch {
            present(error: "The Highdeas engine could not restart: \(error.localizedDescription)")
            return
        }
        waitForEngineThenLoad()
    }

    func applicationWillTerminate(_ notification: Notification) {
        engine?.terminate()
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.terminate(nil)
    }

    // MARK: - Loading and self-healing

    private var inboxURL: URL { URL(string: "http://127.0.0.1:\(port)/")! }

    private func waitForEngineThenLoad() {
        var request = URLRequest(url: inboxURL)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    // Serving again: the allowance is for an engine that won't
                    // stay up, not a running total over a week-long session.
                    self.engineStarts = 0
                    self.webView.load(URLRequest(url: self.inboxURL))
                } else {
                    // Not serving yet. Never a deadline: a live engine that
                    // hasn't answered is *starting* — it fetches from origin,
                    // may pull, may run pip, all before it binds its port, and a
                    // slow network makes that a minute. An engine that has
                    // genuinely died is the termination handler's business, not
                    // a stopwatch's. (A 16-second cap here quit the app on a
                    // launch that was merely updating.)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                        self.waitForEngineThenLoad()
                    }
                }
            }
        }.resume()
    }

    /// How many engines the shell will start before it stops trying and says so.
    /// Reset by any spell of actually serving, so this catches a crash loop
    /// rather than a long session that saw one update.
    private static let engineAttempts = 4

    /// Any failed navigation means the engine is between lives (a self-update
    /// re-exec) or not yet up: show the splash and keep knocking.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        webView.loadHTMLString(Splash.html, baseURL: nil)
        waitForEngineThenLoad()
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        webView.loadHTMLString(Splash.html, baseURL: nil)
        waitForEngineThenLoad()
    }

    private func present(error message: String) {
        let alert = NSAlert()
        alert.messageText = "Highdeas"
        alert.informativeText = message
        alert.runModal()
        NSApp.terminate(nil)
    }
}
