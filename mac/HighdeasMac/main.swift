// The native shell: a real macOS app that owns the Highdeas window and runs
// the Python engine as its child. Everything the user sees is the same local
// web app; what macOS sees is a first-class citizen — real Dock identity,
// real icon treatment in every animation, real window frame persistence.
//
// main.swift construction (no storyboard, no @main): the classic explicit
// bootstrap keeps the bundle free of principal-class plist ceremony.
import AppKit

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
