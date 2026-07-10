// swift-tools-version: 6.0
// The pure logic of the capture app — the upload queue's bookkeeping and the
// HTTP contract with the Highdeas server — kept in a package so it can be
// tested headlessly on a Mac, away from the audio hardware and the UI.
import PackageDescription

let package = Package(
    name: "HighdeasKit",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "HighdeasKit", targets: ["HighdeasKit"]),
    ],
    targets: [
        .target(name: "HighdeasKit", swiftSettings: [.swiftLanguageMode(.v5)]),
        .testTarget(
            name: "HighdeasKitTests",
            dependencies: ["HighdeasKit"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
