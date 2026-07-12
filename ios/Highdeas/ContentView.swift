import SwiftUI
import HighdeasKit

struct ContentView: View {
    @EnvironmentObject private var model: CaptureModel
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            Group {
                if model.items.isEmpty {
                    ContentUnavailableView(
                        "Nothing waiting",
                        systemImage: "checkmark.circle",
                        description: Text("Recordings appear here until the server confirms them."))
                } else {
                    List(model.items) { item in
                        RecordingRow(item: item)
                    }
                }
            }
            .navigationTitle("Highdeas")
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if model.endpoints.isEmpty {
                        Label("Server not configured", systemImage: "exclamationmark.triangle")
                            .labelStyle(.iconOnly)
                            .foregroundStyle(.orange)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: {
                        Image(systemName: "gearshape")
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                RecordButton()
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .alert("Recording couldn't start",
                   isPresented: Binding(get: { model.recordingProblem != nil },
                                        set: { if !$0 { model.recordingProblem = nil } })) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(model.recordingProblem ?? "")
            }
        }
    }
}

private struct RecordingRow: View {
    @EnvironmentObject private var model: CaptureModel
    @StateObject private var player = Player()
    @State private var expanded = false
    let item: RecordingItem

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.recordedAt, format: .dateTime.month(.abbreviated).day()
                        .hour().minute())
                        .font(.headline)
                    StateLine(state: item.state)
                }
                Spacer()
                if item.state != .recording {
                    Button {
                        toggleExpanded()
                    } label: {
                        Image(systemName: expanded ? "chevron.down.circle" : "play.circle")
                            .font(.title2)
                    }
                    .buttonStyle(.borderless)
                }
            }
            if expanded {
                ScrubBar(player: player)
            }
        }
        .padding(.vertical, 2)
        .onDisappear { player.stop() }
    }

    private func toggleExpanded() {
        expanded.toggle()
        if expanded {
            player.load(item.url)
            player.toggle()
        } else {
            player.stop()
        }
    }
}

private struct StateLine: View {
    let state: RecordingItem.State

    var body: some View {
        switch state {
        case .recording:
            Label("Recording…", systemImage: "waveform")
                .font(.caption).foregroundStyle(.red)
        case .uploading:
            Label("Uploading…", systemImage: "arrow.up.circle")
                .font(.caption).foregroundStyle(.blue)
        case .awaitingMachine:
            Label("Will sync next time Highdeas is open on a computer",
                  systemImage: "arrow.up.circle.dotted")
                .font(.caption).foregroundStyle(.secondary)
        case .queued:
            Label("Queued", systemImage: "clock")
                .font(.caption).foregroundStyle(.secondary)
        case .blocked(let reason):
            Label(reason, systemImage: "exclamationmark.triangle")
                .font(.caption).foregroundStyle(.orange)
        }
    }
}

private struct ScrubBar: View {
    @ObservedObject var player: Player

    var body: some View {
        HStack(spacing: 12) {
            Button { player.toggle() } label: {
                Image(systemName: player.isPlaying ? "pause.fill" : "play.fill")
            }
            .buttonStyle(.borderless)
            Slider(value: $player.position, in: 0...player.duration) { editing in
                player.scrub(editing: editing)
            }
            Text(timeString(player.position))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
        }
    }

    private func timeString(_ seconds: TimeInterval) -> String {
        let whole = Int(seconds.rounded())
        return String(format: "%d:%02d", whole / 60, whole % 60)
    }
}

private struct RecordButton: View {
    @EnvironmentObject private var model: CaptureModel

    var body: some View {
        VStack(spacing: 6) {
            Button {
                model.toggleRecording()
            } label: {
                ZStack {
                    Circle()
                        .stroke(.red.opacity(0.4), lineWidth: 4)
                        .frame(width: 76, height: 76)
                    if model.recorder.isRecording {
                        RoundedRectangle(cornerRadius: 8)
                            .fill(.red)
                            .frame(width: 34, height: 34)
                    } else {
                        Circle()
                            .fill(.red)
                            .frame(width: 62, height: 62)
                    }
                }
            }
            .buttonStyle(.plain)
            if model.recorder.isRecording {
                Text(timeString(model.recorder.elapsed))
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.red)
            }
        }
        // Room above as below: with no top inset the bar's edge ran exactly
        // through the button's halo, reading as a button bursting out of it.
        .padding(.top, 14)
        .padding(.bottom, 10)
        .frame(maxWidth: .infinity)
        .background(.bar)
    }

    private func timeString(_ seconds: TimeInterval) -> String {
        let whole = Int(seconds.rounded())
        return String(format: "%d:%02d", whole / 60, whole % 60)
    }
}

private struct SettingsView: View {
    @EnvironmentObject private var model: CaptureModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.1.23:5055", text: $model.serverURLs, axis: .vertical)
                        .lineLimit(1...4)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } header: {
                    Text("Server URLs — one per line")
                } footer: {
                    Text("Every machine that runs Highdeas (LAN or Tailscale address). Recordings push to all of them; the shared store keeps just one copy.")
                }
                Section {
                    TextField("Upload token", text: $model.uploadToken)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                } header: {
                    Text("Token")
                } footer: {
                    Text("Must match HIGHDEAS_UPLOAD_TOKEN in the PC's .env.")
                }
                if model.endpoints.isEmpty {
                    Text("Recordings will wait on the phone until both fields are set.")
                        .font(.footnote)
                        .foregroundStyle(.orange)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
