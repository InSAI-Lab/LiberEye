#if !LIBEREYE_WITH_HEYCYAN
import Foundation
import CoreBluetooth
import Combine
import UIKit

/// App-owned device shape; no implementation or headers from the vendor SDK.
struct GlassesDiscoveredDevice {
    let peripheral: CBPeripheral
    let mac: String
}

/// Public builds expose phone capture and wrist feedback without simulating glasses hardware.
@MainActor
final class HeyCyanService: NSObject, ObservableObject {
    static let shared = HeyCyanService()
    static let unavailableMessage = "Glasses connectivity is unavailable in this build. Use the phone camera"
    @Published var deviceState: HeyCyanDeviceState = .unbind
    @Published var isScanning = false
    @Published var discoveredDevices: [GlassesDiscoveredDevice] = []
    @Published var statusMessage = unavailableMessage
    @Published var batteryLevel = 0
    @Published var isCharging = false
    @Published var connectedDeviceName = ""
    @Published var photoCount = 0
    @Published var videoCount = 0
    @Published var audioCount = 0
    @Published var latestGlassesPhoto: UIImage?
    @Published var isTakingPhoto = false
    @Published var isDownloading = false
    @Published var downloadProgress: Float = 0
    @Published var isLivePreviewActive = false
    @Published var livePreviewStatus = unavailableMessage
    @Published var livePreviewError: String?
    @Published var livePreviewFrameCount = 0
    @Published var lastPreviewFrameAt: Date?
    @Published var isPreparingWifi = false
    @Published var isWifiReady = false
    @Published var wifiSSID = ""
    @Published var wifiPassword = ""
    @Published var deviceWifiIP = ""
    var pendingFrameMessageAvailable: Bool { false }
    var isBluetoothReady: Bool { false }

    func reportUnavailable() { statusMessage = Self.unavailableMessage }
    func refreshConnectionStatus(autoConnect: Bool = false) { reportUnavailable() }
    func autoConnectIfNeeded() { reportUnavailable() }
    func startScanning(autoConnectPaired: Bool = false) { reportUnavailable() }
    func stopScanning() { isScanning = false }
    func connect(_ peripheral: GlassesDiscoveredDevice) { reportUnavailable() }
    func disconnect() { deviceState = .unbind }
    func getDeviceInfo() { reportUnavailable() }
    func getBattery() { reportUnavailable() }
    func getMediaInfo() { reportUnavailable() }
    func takePhoto() { reportUnavailable() }
    func takeAIPhoto() { reportUnavailable() }
    func startLivePreview() { reportUnavailable() }
    func stopLivePreview() { isLivePreviewActive = false }
    func boostGlassesVolumeForPlayback() {}
    func captureCurrentGlassesFrame() async -> UIImage? { reportUnavailable(); return nil }
    func prepareWifiForMediaTransfer() { reportUnavailable() }
    func refreshDeviceWifiIP() { reportUnavailable() }
    func getLatestThumbnail() { reportUnavailable() }
    func downloadThumbnail(at index: Int) { reportUnavailable() }
    func downloadAllMedia() { reportUnavailable() }
}
#endif
