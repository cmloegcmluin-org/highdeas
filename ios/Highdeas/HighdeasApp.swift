import SwiftUI

/// The one UIKit hook SwiftUI can't express: the system relaunching the app
/// to deliver background-upload outcomes. The uploader must reattach to its
/// session and, once the events drain, call the parked handler back.
final class AppLifecycle: NSObject, UIApplicationDelegate {
    static weak var model: CaptureModel?

    func application(_ application: UIApplication,
                     handleEventsForBackgroundURLSession identifier: String,
                     completionHandler: @escaping () -> Void) {
        Task { @MainActor in
            AppLifecycle.model?.uploader.backgroundCompletionHandler = completionHandler
            AppLifecycle.model?.uploader.reconnect()
        }
    }
}

@main
struct HighdeasApp: App {
    @UIApplicationDelegateAdaptor(AppLifecycle.self) private var lifecycle
    @StateObject private var model = CaptureModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onAppear { AppLifecycle.model = model }
        }
        .onChange(of: scenePhase) { _, phase in
            // Coming back to the foreground is the natural moment a memo
            // recorded away from home finally reaches the server — and the
            // moment to re-ask for Local Network access if it's missing.
            if phase == .active {
                model.wake()
                model.nudgeLocalNetwork()
            }
        }
    }
}
