// swift-tools-version:5.9
// DiBeKho for macOS in Swift (work in progress, private repo). The Windows app stays the Python one; both read the
// same data folder, the same .dibekho packages and the same cloud, so the schema comes from the Python app
// (tools/gen_from_python.py) and this app never writes a schema newer than the Python app reads.
import PackageDescription

let package = Package(
    name: "DiBeKhoMac",
    platforms: [.macOS(.v13)],  // as the Python app (PySide6 6.10)
    products: [
        .executable(name: "DiBeKhoSwift", targets: ["DiBeKhoSwift"]),
    ],
    dependencies: [
        // MIT. 6.x builds with Xcode 15 and 16 (7.x needs Xcode 16 / Swift 6)
        .package(url: "https://github.com/groue/GRDB.swift.git", .upToNextMajor(from: "6.29.0")),
        // MIT: reads the .xlsx zip (the XML inside is read with Foundation's XMLParser)
        .package(url: "https://github.com/weichsel/ZIPFoundation.git", .upToNextMajor(from: "0.9.19")),
    ],
    targets: [
        .target(name: "DiBeKhoCore", dependencies: [
            .product(name: "GRDB", package: "GRDB.swift"),
            .product(name: "ZIPFoundation", package: "ZIPFoundation"),
        ]),
        .executableTarget(name: "DiBeKhoSwift", dependencies: ["DiBeKhoCore"]),
        .testTarget(name: "DiBeKhoCoreTests", dependencies: ["DiBeKhoCore"], exclude: ["XlsxRef"], resources: [.copy("Notes"), .copy("ScanNotes"), .copy("InboxFiles")]),
    ]
)
