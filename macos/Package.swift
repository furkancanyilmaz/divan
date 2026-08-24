// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "Divan",
    defaultLocalization: "tr",
    platforms: [
        .macOS(.v13),
    ],
    products: [
        .executable(name: "Divan", targets: ["DivanNative"]),
    ],
    targets: [
        .executableTarget(
            name: "DivanNative",
            path: "Sources/DivanNative",
            linkerSettings: [
                .linkedFramework("Security"),
            ]
        ),
        .testTarget(
            name: "DivanNativeTests",
            dependencies: ["DivanNative"],
            path: "Tests/DivanNativeTests",
            resources: [.copy("Fixtures")]
        ),
    ]
)
