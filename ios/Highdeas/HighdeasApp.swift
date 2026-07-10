import SwiftUI

@main
struct HighdeasApp: App {
    @StateObject private var model = CaptureModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
        .onChange(of: scenePhase) { _, phase in
            // Coming back to the foreground is the natural moment a memo
            // recorded away from home finally reaches the server.
            if phase == .active { model.wake() }
        }
    }
}
