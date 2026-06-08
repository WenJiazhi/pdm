// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "PDM",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "PDM", targets: ["PDM"])
    ],
    targets: [
        .executableTarget(
            name: "PDM",
            path: "Sources/PDM"
        )
    ]
)
