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

        engineStarts = 1
        do {
            engine = try Engine.launch(port: port)
        } catch {
            present(error: "The Highdeas engine could not start: \(error.localizedDescription)")
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

    private func waitForEngineThenLoad(attempt: Int = 0) {
        var request = URLRequest(url: inboxURL)
        request.timeoutInterval = 1
        URLSession.shared.dataTask(with: request) { _, response, _ in
            DispatchQueue.main.async {
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    // Serving again: the allowance is for an engine that won't
                    // stay up, not a running total over a week-long session.
                    self.engineStarts = 0
                    self.webView.load(URLRequest(url: self.inboxURL))
                } else if self.engine?.isRunning != true {
                    // The engine is gone. During startup that means it never came
                    // up; later it means it died — a self-update whose re-exec
                    // didn't take, most often. Either way the shell used to sit on
                    // the splash forever, a window doing nothing with no way to
                    // say so, because nothing here ever started a second engine.
                    // So start one, and only give up if that keeps failing too.
                    self.restartEngine(attempt: attempt)
                } else {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                        self.waitForEngineThenLoad(attempt: attempt + 1)
                    }
                }
            }
        }.resume()
    }

    /// How many times the shell will start an engine that won't stay up before it
    /// stops trying and says so. Generous: a machine mid-update can take a moment.
    private static let engineAttempts = 3

    private func restartEngine(attempt: Int) {
        guard engineStarts < Self.engineAttempts else {
            if attempt > 3 {
                present(error: "The Highdeas engine keeps exiting. "
                        + "Try running it by hand to see why:\n\n"
                        + "\(Engine.repo.path)/.venv/bin/python -m highdeas.app")
            }
            return
        }
        engineStarts += 1
        do {
            engine = try Engine.launch(port: port)
        } catch {
            present(error: "The Highdeas engine could not start: \(error.localizedDescription)")
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.waitForEngineThenLoad(attempt: attempt + 1)
        }
    }

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
