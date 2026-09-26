//
//  HeyCyanService.swift
//  LiberEye
//
//  HeyCyan smart glasses service wrapping the vendor SDK.
//

import Foundation
import CoreBluetooth
import Combine
import UIKit

// MARK: - Device state
enum HeyCyanDeviceState: String {
    case unknown = "Unknown"
    case unbind = "Unbound"
    case connecting = "Connecting"
    case connected = "Connected"
    case disconnecting = "Disconnecting"
    case disconnected = "Disconnected"

    var displayText: String {
        let language = AppLanguageManager.shared
        switch self {
        case .unknown: return language.text("unknown")
        case .unbind: return language.text("unbound")
        case .connecting: return language.text("connecting")
        case .connected: return language.text("connected")
        case .disconnecting: return language.text("disconnecting")
        case .disconnected: return language.text("disconnected")
        }
    }
}

#if LIBEREYE_WITH_HEYCYAN
typealias GlassesDiscoveredDevice = QCBlePeripheral

// MARK: - HeyCyan service
@MainActor
class HeyCyanService: NSObject, ObservableObject {
    static let shared = HeyCyanService()

    private struct DeviceVolumeSnapshot {
        let musicMin: Int
        let musicCurrent: Int
        let callMin: Int
        let callCurrent: Int
        let systemMin: Int
        let systemCurrent: Int
        let mode: QCVolumeMode
    }

    @Published var deviceState: HeyCyanDeviceState = .unknown
    @Published var isScanning: Bool = false
    @Published var discoveredDevices: [QCBlePeripheral] = []
    @Published var statusMessage: String = "Tap Scan to find glasses"
    @Published var batteryLevel: Int = 0
    @Published var isCharging: Bool = false
    @Published var connectedDeviceName: String = ""

    // Media state
    @Published var photoCount: Int = 0
    @Published var videoCount: Int = 0
    @Published var audioCount: Int = 0
    @Published var latestGlassesPhoto: UIImage?
    @Published var isTakingPhoto: Bool = false
    @Published var isDownloading: Bool = false
    @Published var downloadProgress: Float = 0
    @Published var isLivePreviewActive: Bool = false
    @Published var livePreviewStatus: String = "Live preview is off"
    @Published var livePreviewError: String?
    @Published var livePreviewFrameCount: Int = 0
    @Published var lastPreviewFrameAt: Date?
    @Published var isPreparingWifi: Bool = false
    @Published var isWifiReady: Bool = false
    @Published var wifiSSID: String = ""
    @Published var wifiPassword: String = ""
    @Published var deviceWifiIP: String = ""

    private var centralManager: CBCentralManager!
    private var connectedPeripheral: CBPeripheral?
    private var livePreviewTimer: Timer?
    private var pendingLiveFrameRequest = false
    private var livePreviewRequestID = 0
    private var pendingFrameContinuation: CheckedContinuation<UIImage?, Never>?
    private var autoConnectOnNextScan = false
    private var didRequestInitialAutoConnect = false
    private var previewVolumeSnapshot: DeviceVolumeSnapshot?
    private var isPreviewAudioMuted = false
    private var lastPlaybackVolumeBoostAt: Date?
    private let livePreviewInterval: TimeInterval = 0.45
    private let livePreviewTimeout: TimeInterval = 8.0
    private let frameCaptureTimeout: TimeInterval = 10.0
    private let preferredGlassesNameKeywords = ["m02", "heyc", "cyan", "glass", "glasses", "qc", "o_"]

    var pendingFrameMessageAvailable: Bool {
        pendingLiveFrameRequest || isTakingPhoto || livePreviewStatus.lowercased().contains("transferring") || livePreviewStatus.lowercased().contains("waiting")
    }

    override init() {
        super.init()
        guard !AppRuntime.isRunningForPreviews else {
            deviceState = .unbind
            statusMessage = "Preview mode"
            return
        }
        // Set the SDK delegates during initialization.
        QCCentralManager.shared().delegate = self
        QCSDKManager.shareInstance().delegate = self
        centralManager = CBCentralManager(delegate: self, queue: nil)

        refreshConnectionStatus()
    }

    // MARK: - Synchronize SDK connection state
    func refreshConnectionStatus(autoConnect: Bool = false) {
        guard !AppRuntime.isRunningForPreviews else { return }
        QCCentralManager.shared().delegate = self
        QCSDKManager.shareInstance().delegate = self

        let sdkState = QCCentralManager.shared().deviceState
        print("[HeyCyan] Current SDK state: \(sdkState.rawValue)")

        switch sdkState {
        case .connected:
            stopScanning()
            applyConnectedState(peripheral: QCCentralManager.shared().connectedPeripheral)
        case .connecting:
            deviceState = .connecting
            statusMessage = "Connecting..."
        default:
            if deviceState != .connected && deviceState != .connecting {
                deviceState = .unbind
                statusMessage = autoConnect ? "Looking for connected glasses..." : "No glasses connected"
            }
            if autoConnect {
                startScanning(autoConnectPaired: true)
            }
        }
    }

    func autoConnectIfNeeded() {
        guard !AppRuntime.isRunningForPreviews else { return }
        guard !didRequestInitialAutoConnect else { return }
        guard isSDKBluetoothReady else { return }
        didRequestInitialAutoConnect = true
        refreshConnectionStatus(autoConnect: true)
    }

    // MARK: - Bluetooth readiness
    var isBluetoothReady: Bool {
        guard !AppRuntime.isRunningForPreviews else { return false }
        return centralManager?.state == .poweredOn || QCCentralManager.shared().bleState == .poweredOn
    }

    private var isSDKBluetoothReady: Bool {
        guard !AppRuntime.isRunningForPreviews else { return false }
        return QCCentralManager.shared().bleState == .poweredOn
    }

    // MARK: - Start scanning
    func startScanning(autoConnectPaired: Bool = false) {
        guard !AppRuntime.isRunningForPreviews else { return }
        guard isBluetoothReady else {
            statusMessage = "Turn on Bluetooth"
            return
        }

        guard isSDKBluetoothReady else {
            statusMessage = "Initializing Bluetooth. Please wait"
            return
        }

        autoConnectOnNextScan = autoConnectPaired
        statusMessage = autoConnectPaired ? "Looking for M02_9440 glasses..." : "Scanning..."
        isScanning = true
        discoveredDevices.removeAll()

        // Use the SDK scan method.
        QCCentralManager.shared().delegate = self
        QCCentralManager.shared().scan(withTimeout: autoConnectPaired ? 6 : 15)
    }

    // MARK: - Stop scanning
    func stopScanning() {
        guard !AppRuntime.isRunningForPreviews else { return }
        isScanning = false
        autoConnectOnNextScan = false
        QCCentralManager.shared().stopScan()
        statusMessage = "Scan stopped"
    }

    // MARK: - Connect to a device
    func connect(_ peripheral: QCBlePeripheral) {
        let cbPeripheral = peripheral.peripheral
        autoConnectOnNextScan = false
        isScanning = false
        QCCentralManager.shared().stopScan()
        connectedPeripheral = cbPeripheral
        deviceState = .connecting
        statusMessage = "Connecting to \(cbPeripheral.name ?? "device")..."

        // Use the default connect method. Extra ANCS options can stall an M02 connection.
        QCCentralManager.shared().connect(cbPeripheral, timeout: 10)
    }

    // MARK: - Disconnect
    func disconnect() {
        guard connectedPeripheral != nil else { return }
        stopLivePreview()
        deviceState = .disconnecting
        QCCentralManager.shared().remove()
    }

    // MARK: - Read device information
    func getDeviceInfo() {
        QCSDKCmdCreator.getDeviceVersionInfoSuccess({ hdVersion, firmVersion, hdWifiVersion, firmWifiVersion in
            print("Hardware version: \(hdVersion), Firmware version: \(firmVersion)")
            print("Wi-Fi hardware: \(hdWifiVersion), Wi-Fi firmware: \(firmWifiVersion)")
        }, fail: {
            print("Failed to read the device version")
        })
    }

    // MARK: - Read battery status
    func getBattery() {
        QCSDKCmdCreator.getDeviceBattery({ [weak self] battery, charging in
            self?.batteryLevel = battery
            self?.isCharging = charging
            print("Battery: \(battery)%, Charging: \(charging)")
        }, fail: {
            print("Failed to read battery status")
        })
    }

    // MARK: - Read media information
    func getMediaInfo() {
        QCSDKCmdCreator.getDeviceMedia({ [weak self] photo, video, audio, type in
            self?.photoCount = photo
            self?.videoCount = video
            self?.audioCount = audio
            print("Photos: \(photo), Videos: \(video), Audio: \(audio)")
        }, fail: {
            print("Failed to read media information")
        })
    }

    // MARK: - Take a photo
    func takePhoto() {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            return
        }

        isTakingPhoto = true
        statusMessage = "Taking a photo..."

        suppressCaptureAudioIfNeeded { [weak self] in
            QCSDKCmdCreator.setDeviceMode(.photo, success: { [weak self] in
                print("Photo capture command sent")
                // Fetch the thumbnail after taking a photo.
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                    self?.getLatestThumbnail()
                }
            }, fail: { [weak self] mode in
                self?.isTakingPhoto = false
                self?.statusMessage = "Photo capture failed"
                print("Photo capture failed in mode: \(mode)")
            })
        }
    }

    // MARK: - Vision photo capture
    func takeAIPhoto() {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            return
        }

        isTakingPhoto = true
        statusMessage = "Capturing a vision frame..."

        suppressCaptureAudioIfNeeded { [weak self] in
            QCSDKCmdCreator.setDeviceMode(.aiPhoto, success: { [weak self] in
                print("Vision capture command sent")
                DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) {
                    self?.getLatestThumbnail()
                }
            }, fail: { [weak self] mode in
                self?.isTakingPhoto = false
                self?.statusMessage = "Vision capture failed"
                print("Vision capture failed in mode: \(mode)")
            })
        }
    }

    // MARK: - Live preview through QCSDKManagerDelegate image frames
    func startLivePreview() {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            livePreviewError = "Glasses are not connected"
            return
        }

        guard !isLivePreviewActive else { return }

        isLivePreviewActive = true
        livePreviewError = nil
        livePreviewFrameCount = 0
        livePreviewStatus = "Starting live preview with camera sounds muted..."
        suppressCaptureAudioIfNeeded { [weak self] in
            self?.requestLivePreviewFrame(force: true)
        }
    }

    func stopLivePreview() {
        livePreviewTimer?.invalidate()
        livePreviewTimer = nil
        isLivePreviewActive = false
        pendingLiveFrameRequest = false
        isTakingPhoto = false
        livePreviewStatus = "Live preview stopped"
        QCSDKManager.shareInstance().stopAIChat()
        restorePreviewAudioFeedbackIfNeeded(boostAfterRestore: true)
    }

    private func suppressCaptureAudioIfNeeded(completion: (() -> Void)? = nil) {
        QCSDKCmdCreator.setAISpeekModel(.stop) { _, _ in }

        guard !isPreviewAudioMuted else {
            completion?()
            return
        }

        muteSystemVolumeForCapture(completion: completion)
    }

    private func muteSystemVolumeForCapture(completion: (() -> Void)?) {
        QCSDKCmdCreator.getVolumeWithFinished { [weak self] success, _, result in
            DispatchQueue.main.async {
                guard let self, success, let volume = result as? QCVolumeInfoModel else {
                    print("[HeyCyan] Could not read glasses volume; camera sounds cannot be muted before capture")
                    completion?()
                    return
                }

                self.logDeviceVolume(volume, prefix: "Volume before capture")

                self.previewVolumeSnapshot = DeviceVolumeSnapshot(
                    musicMin: volume.musicMin,
                    musicCurrent: volume.musicCurrent,
                    callMin: volume.callMin,
                    callCurrent: volume.callCurrent,
                    systemMin: volume.systemMin,
                    systemCurrent: volume.systemCurrent,
                    mode: volume.mode
                )

                self.tryMuteCaptureVolumes(from: volume, completion: completion)
            }
        }
    }

    private func tryMuteCaptureVolumes(from currentVolume: QCVolumeInfoModel, completion: (() -> Void)?) {
        let candidates: [(mode: QCVolumeMode, target: Int, label: String)] = [
            (.system, 0, "system mode, all current=0"),
            (.music, 0, "music mode, all current=0"),
            (.call, 0, "call mode, all current=0"),
            (.system, currentVolume.systemMin, "system mode, all current=minimum")
        ]

        applyMuteCandidate(candidates, index: 0, basedOn: currentVolume, completion: completion)
    }

    private func applyMuteCandidate(
        _ candidates: [(mode: QCVolumeMode, target: Int, label: String)],
        index: Int,
        basedOn currentVolume: QCVolumeInfoModel,
        completion: (() -> Void)?
    ) {
        guard index < candidates.count else {
            print("[HeyCyan] Volume readback is unchanged after repeated setVolume calls; the app may not control camera sounds")
            completion?()
            return
        }

        let candidate = candidates[index]
        setCaptureVolume(from: currentVolume, mode: candidate.mode, target: candidate.target, label: candidate.label) { [weak self] success in
            guard let self else { return }

            guard success else {
                self.applyMuteCandidate(candidates, index: index + 1, basedOn: currentVolume, completion: completion)
                return
            }

            self.verifyCaptureVolumeMuted(expectedTarget: candidate.target) { [weak self] muted in
                guard let self else { return }
                if muted {
                    completion?()
                } else {
                    self.applyMuteCandidate(candidates, index: index + 1, basedOn: currentVolume, completion: completion)
                }
            }
        }
    }

    private func setCaptureVolume(
        from currentVolume: QCVolumeInfoModel,
        mode: QCVolumeMode,
        target: Int,
        label: String,
        completion: @escaping (Bool) -> Void
    ) {
        let muted = QCVolumeInfoModel()
        muted.musicMin = currentVolume.musicMin
        muted.musicMax = currentVolume.musicMax
        muted.musicCurrent = clampedVolume(target, min: currentVolume.musicMin, max: currentVolume.musicMax)
        muted.callMin = currentVolume.callMin
        muted.callMax = currentVolume.callMax
        muted.callCurrent = clampedVolume(target, min: currentVolume.callMin, max: currentVolume.callMax)
        muted.systemMin = currentVolume.systemMin
        muted.systemMax = currentVolume.systemMax
        muted.systemCurrent = clampedVolume(target, min: currentVolume.systemMin, max: currentVolume.systemMax)
        muted.mode = mode

        QCSDKCmdCreator.setVolume(muted) { success, error, _ in
            DispatchQueue.main.async {
                if let error {
                    print("[HeyCyan] setVolume(\(label)) error: \(error.localizedDescription)")
                }
                print("[HeyCyan] setVolume(\(label)) success=\(success), mode=\(mode.rawValue), music=\(muted.musicCurrent), call=\(muted.callCurrent), system=\(muted.systemCurrent)")
                completion(success)
            }
        }
    }

    private func clampedVolume(_ value: Int, min: Int, max: Int) -> Int {
        Swift.max(min, Swift.min(value, max))
    }

    private func verifyCaptureVolumeMuted(expectedTarget: Int, completion: @escaping (Bool) -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            QCSDKCmdCreator.getVolumeWithFinished { [weak self] success, _, result in
                DispatchQueue.main.async {
                    guard let self else { return }

                    guard success, let volume = result as? QCVolumeInfoModel else {
                        self.isPreviewAudioMuted = true
                        print("[HeyCyan] setVolume succeeded but volume verification failed; continuing capture")
                        completion(true)
                        return
                    }

                    self.logDeviceVolume(volume, prefix: "Volume after muting")

                    let muted = volume.musicCurrent == expectedTarget
                        || volume.callCurrent == expectedTarget
                        || volume.systemCurrent == expectedTarget
                        || volume.systemCurrent == volume.systemMin

                    self.isPreviewAudioMuted = muted
                    if muted {
                        print("[HeyCyan] Glasses volume reduction confirmed: music=\(volume.musicCurrent), call=\(volume.callCurrent), system=\(volume.systemCurrent)")
                        if self.isLivePreviewActive {
                            self.livePreviewStatus = "Live preview is on with glasses notification volume reduced"
                        }
                    } else {
                        print("[HeyCyan] Volume readback did not decrease after setVolume: music=\(volume.musicCurrent), call=\(volume.callCurrent), system=\(volume.systemCurrent)")
                    }
                    completion(muted)
                }
            }
        }
    }

    private func logDeviceVolume(_ volume: QCVolumeInfoModel, prefix: String) {
        print("[HeyCyan] \(prefix): music \(volume.musicCurrent)/\(volume.musicMin)-\(volume.musicMax), call \(volume.callCurrent)/\(volume.callMin)-\(volume.callMax), system \(volume.systemCurrent)/\(volume.systemMin)-\(volume.systemMax), mode=\(volume.mode.rawValue)")
    }

    func boostGlassesVolumeForPlayback() {
        raiseGlassesVolumeForPlayback()
    }

    private func raiseGlassesVolumeForPlayback() {
        guard deviceState == .connected else { return }
        if let lastPlaybackVolumeBoostAt,
           Date().timeIntervalSince(lastPlaybackVolumeBoostAt) < 5 {
            return
        }
        lastPlaybackVolumeBoostAt = Date()

        QCSDKCmdCreator.getVolumeWithFinished { [weak self] success, _, result in
            DispatchQueue.main.async {
                guard self != nil, success, let volume = result as? QCVolumeInfoModel else {
                    print("[HeyCyan] Could not read glasses volume; playback volume cannot be increased")
                    return
                }

                let raised = QCVolumeInfoModel()
                raised.musicMin = volume.musicMin
                raised.musicMax = volume.musicMax
                raised.musicCurrent = volume.musicMax
                raised.callMin = volume.callMin
                raised.callMax = volume.callMax
                raised.callCurrent = volume.callMax
                raised.systemMin = volume.systemMin
                raised.systemMax = volume.systemMax
                raised.systemCurrent = volume.systemMax
                raised.mode = .music

                QCSDKCmdCreator.setVolume(raised) { success, error, _ in
                    DispatchQueue.main.async {
                        if let error {
                            print("[HeyCyan] Failed to increase glasses volume: \(error.localizedDescription)")
                        }
                        print("[HeyCyan] Increase glasses volume success=\(success), music=\(raised.musicCurrent), call=\(raised.callCurrent), system=\(raised.systemCurrent)")
                    }
                }
            }
        }
    }

    private func restorePreviewAudioFeedbackIfNeeded(boostAfterRestore: Bool = false) {
        guard isPreviewAudioMuted, let snapshot = previewVolumeSnapshot else {
            previewVolumeSnapshot = nil
            isPreviewAudioMuted = false
            if boostAfterRestore {
                raiseGlassesVolumeForPlayback()
            }
            return
        }

        QCSDKCmdCreator.getVolumeWithFinished { [weak self] success, _, result in
            DispatchQueue.main.async {
                guard let self else { return }
                defer {
                    self.previewVolumeSnapshot = nil
                    self.isPreviewAudioMuted = false
                }

                guard success, let volume = result as? QCVolumeInfoModel else { return }

                let restored = QCVolumeInfoModel()
                restored.musicMin = volume.musicMin
                restored.musicMax = volume.musicMax
                restored.musicCurrent = boostAfterRestore ? volume.musicMax : snapshot.musicCurrent
                restored.callMin = volume.callMin
                restored.callMax = volume.callMax
                restored.callCurrent = boostAfterRestore ? volume.callMax : snapshot.callCurrent
                restored.systemMin = volume.systemMin
                restored.systemMax = volume.systemMax
                restored.systemCurrent = boostAfterRestore ? volume.systemMax : snapshot.systemCurrent
                restored.mode = snapshot.mode

                QCSDKCmdCreator.setVolume(restored) { _, _, _ in }
            }
        }
    }

    func captureCurrentGlassesFrame() async -> UIImage? {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            return nil
        }

        if let image = latestGlassesPhoto,
           let lastPreviewFrameAt,
           Date().timeIntervalSince(lastPreviewFrameAt) < 3 {
            return image
        }

        let requestStartedAt = Date()
        return await withCheckedContinuation { continuation in
            pendingFrameContinuation?.resume(returning: nil)
            pendingFrameContinuation = continuation
            if pendingLiveFrameRequest {
                livePreviewStatus = "Waiting for the glasses photo..."
            } else {
                requestLivePreviewFrame(force: true)
            }

            DispatchQueue.main.asyncAfter(deadline: .now() + frameCaptureTimeout) { [weak self] in
                guard let self, self.pendingFrameContinuation != nil else { return }
                if let latestGlassesPhoto = self.latestGlassesPhoto,
                   let lastPreviewFrameAt = self.lastPreviewFrameAt,
                   lastPreviewFrameAt >= requestStartedAt {
                    self.finishPendingFrameCapture(with: latestGlassesPhoto)
                    return
                }

                self.livePreviewStatus = "The glasses photo is still transferring. Try again shortly"
                self.pendingLiveFrameRequest = false
                self.isTakingPhoto = false
                self.finishPendingFrameCapture(with: nil)
            }
        }
    }

    private func requestLivePreviewFrame(force: Bool = false) {
        guard deviceState == .connected else {
            stopLivePreview()
            livePreviewError = "Glasses disconnected"
            return
        }

        guard force || !pendingLiveFrameRequest else { return }

        if !force && !QCSDKCmdCreator.isPeripheralFreeNow() {
            livePreviewStatus = "Glasses busy, waiting for the next frame..."
            scheduleNextLivePreviewFrame(after: livePreviewInterval)
            return
        }

        pendingLiveFrameRequest = true
        livePreviewRequestID += 1
        let requestID = livePreviewRequestID

        if isLivePreviewActive && !isPreviewAudioMuted {
            suppressCaptureAudioIfNeeded()
        }

        if !isLivePreviewActive {
            isTakingPhoto = true
        }
        livePreviewStatus = isLivePreviewActive ? "Refreshing the glasses frame..." : "Fetching a glasses frame..."

        suppressCaptureAudioIfNeeded { [weak self] in
            QCSDKCmdCreator.setDeviceMode(.aiPhoto, success: { [weak self] in
                DispatchQueue.main.async {
                    self?.livePreviewStatus = "Waiting for a glasses image..."
                }
            }, fail: { [weak self] mode in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.pendingLiveFrameRequest = false
                    self.isTakingPhoto = false
                    self.livePreviewError = "The current glasses mode is unavailable: \(mode)"
                    self.livePreviewStatus = "Frame capture failed"
                    self.finishPendingFrameCapture(with: nil)
                    self.scheduleNextLivePreviewFrame(after: self.livePreviewInterval)
                }
            })
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + livePreviewTimeout) { [weak self] in
            guard let self,
                  self.livePreviewRequestID == requestID,
                  self.pendingLiveFrameRequest else { return }

            if self.pendingFrameContinuation == nil {
                self.pendingLiveFrameRequest = false
                self.isTakingPhoto = false
            }
            self.livePreviewStatus = self.isLivePreviewActive ? "Previous frame timed out. Retrying..." : "Glasses frame request timed out"
            self.scheduleNextLivePreviewFrame(after: self.livePreviewInterval)
        }
    }

    private func scheduleNextLivePreviewFrame(after delay: TimeInterval) {
        guard isLivePreviewActive else { return }

        livePreviewTimer?.invalidate()
        livePreviewTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.requestLivePreviewFrame()
            }
        }
    }

    // MARK: - Prepare glasses Wi-Fi for media downloads
    func prepareWifiForMediaTransfer() {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            return
        }

        guard !isPreparingWifi else { return }

        isPreparingWifi = true
        isWifiReady = false
        livePreviewError = nil
        statusMessage = "Enabling glasses Wi-Fi..."

        QCSDKCmdCreator.openWifi(with: .transfer, success: { [weak self] ssid, password in
            DispatchQueue.main.async {
                guard let self else { return }
                self.wifiSSID = ssid
                self.wifiPassword = password
                self.isPreparingWifi = false
                self.isWifiReady = false
                self.statusMessage = ssid.isEmpty
                    ? "Glasses Wi-Fi is enabled. Connect manually, then refresh the IP address"
                    : "Glasses Wi-Fi enabled: \(ssid)"
            }
        }, fail: { [weak self] code in
            DispatchQueue.main.async {
                self?.isPreparingWifi = false
                self?.isWifiReady = false
                self?.statusMessage = "Failed to enable glasses Wi-Fi"
                self?.livePreviewError = "Failed to enable Wi-Fi: \(code)"
            }
        })
    }

    func refreshDeviceWifiIP() {
        QCSDKCmdCreator.getDeviceWifiIPSuccess({ [weak self] ip in
            DispatchQueue.main.async {
                guard let self else { return }
                self.isPreparingWifi = false
                self.deviceWifiIP = ip ?? ""
                self.isWifiReady = !(ip ?? "").isEmpty
                self.statusMessage = self.isWifiReady ? "Glasses Wi-Fi is ready" : "Glasses IP address unavailable"
                if let ip, !ip.isEmpty {
                    self.probeLocalMediaService(ip: ip)
                }
            }
        }, failed: { [weak self] in
            DispatchQueue.main.async {
                self?.isPreparingWifi = false
                self?.isWifiReady = false
                self?.statusMessage = "Could not read the glasses IP address. Check that the phone is connected to glasses Wi-Fi"
            }
        })
    }

    private func probeLocalMediaService(ip: String) {
        guard let url = URL(string: "http://\(ip)/files/photo") else { return }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3

        URLSession.shared.dataTask(with: request) { [weak self] _, _, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error {
                    self.livePreviewError = "The local media service is temporarily unreachable: \(error.localizedDescription)"
                } else {
                    self.livePreviewError = nil
                }
            }
        }.resume()
    }

    // MARK: - Fetch the latest thumbnail
    func getLatestThumbnail() {
        // Read media information to locate the latest photo.
        QCSDKCmdCreator.getDeviceMedia({ [weak self] photo, video, audio, type in
            self?.photoCount = photo
            self?.videoCount = video
            self?.audioCount = audio

            if photo > 0 {
                // Indices start at zero, so the latest photo index is photo - 1.
                let latestIndex = photo - 1
                self?.downloadThumbnail(at: latestIndex)
            } else {
                self?.isTakingPhoto = false
                self?.statusMessage = "No photos available"
            }
        }, fail: { [weak self] in
            self?.isTakingPhoto = false
            self?.statusMessage = "Failed to read media information"
        })
    }

    // MARK: - Download the thumbnail at an index
    func downloadThumbnail(at index: Int) {
        QCSDKCmdCreator.getThumbnail(index, success: { [weak self] data, width, height in
            self?.isTakingPhoto = false

            if let image = UIImage(data: data) {
                self?.acceptGlassesImage(image, source: "thumbnail")
                self?.statusMessage = "Photo saved"
                print("Thumbnail downloaded: \(width)x\(height)")
            } else {
                self?.statusMessage = "Photo download failed"
            }
        }, fail: { [weak self] in
            self?.isTakingPhoto = false
            self?.statusMessage = "Thumbnail download failed"
            print("Thumbnail download failed")
        })
    }

    // MARK: - Download all media
    func downloadAllMedia() {
        guard deviceState == .connected else {
            statusMessage = "Connect the glasses first"
            return
        }

        isDownloading = true
        downloadProgress = 0
        statusMessage = "Downloading media..."

        let totalCount = photoCount + videoCount + audioCount
        guard totalCount > 0 else {
            isDownloading = false
            statusMessage = "No media files available"
            return
        }

        QCSDKManager.shareInstance().startToDownloadMediaResource(progress: { [weak self] received, expected, progress in
            Task { @MainActor [weak self] in
                self?.downloadProgress = Float(progress)
                self?.statusMessage = "Downloading... \(Int(progress * 100))%"
            }
        }, completion: { [weak self] filePath, error, index, count in
            let statusText: String?
            if let error = error {
                statusText = "Download failed: \(error.localizedDescription)"
            } else if let path = filePath {
                statusText = "Download completed: \(path)"
                print("File \(index + 1)/\(count) downloaded: \(path)")
            } else {
                statusText = nil
            }

            Task { @MainActor [weak self] in
                self?.isDownloading = false
                if let statusText {
                    self?.statusMessage = statusText
                }

                if index == count - 1 {
                    print("All files downloaded")
                }
            }
        })
    }

    private func acceptGlassesImage(_ image: UIImage, source: String) {
        let normalizedImage = image.fixedOrientation()
        let previousFrameAt = lastPreviewFrameAt
        let receivedAt = Date()
        latestGlassesPhoto = normalizedImage
        lastPreviewFrameAt = receivedAt
        pendingLiveFrameRequest = false
        isTakingPhoto = false
        if isLivePreviewActive {
            livePreviewFrameCount += 1
            livePreviewStatus = livePreviewStatusText(source: source, previousFrameAt: previousFrameAt, receivedAt: receivedAt)
            scheduleNextLivePreviewFrame(after: livePreviewInterval)
        } else {
            livePreviewStatus = "Glasses frame received (\(source))"
        }

        finishPendingFrameCapture(with: normalizedImage)
    }

    private func finishPendingFrameCapture(with image: UIImage?) {
        pendingFrameContinuation?.resume(returning: image)
        pendingFrameContinuation = nil
        if !isLivePreviewActive {
            restorePreviewAudioFeedbackIfNeeded(boostAfterRestore: true)
        }
    }

    private func livePreviewStatusText(source: String, previousFrameAt: Date?, receivedAt: Date) -> String {
        guard let previousFrameAt else {
            return "Glasses frame updated (\(source))"
        }

        let interval = receivedAt.timeIntervalSince(previousFrameAt)
        guard interval > 0 else {
            return "Glasses frame updated (\(source))"
        }

        let fps = min(9.9, 1.0 / interval)
        return String(format: "Glasses frame updated (%@, approximately %.1f fps)", source, fps)
    }

    private func isLikelyGlasses(_ device: QCBlePeripheral) -> Bool {
        guard let name = device.peripheral.name?.lowercased(), !name.isEmpty else { return false }
        return preferredGlassesNameKeywords.contains { keyword in
            keyword == "o_" ? name.hasPrefix(keyword) : name.contains(keyword)
        }
    }

    private func preferredAutoConnectDevice(from devices: [QCBlePeripheral]) -> QCBlePeripheral? {
        if let paired = devices.first(where: { $0.isPaired }) {
            return paired
        }

        return devices.first(where: isLikelyGlasses)
    }

    private var sdkConnectedPeripheral: CBPeripheral? {
        QCCentralManager.shared().connectedPeripheral
    }

    private func applyConnectedState(peripheral: CBPeripheral?) {
        deviceState = .connected
        connectedPeripheral = peripheral ?? sdkConnectedPeripheral
        connectedDeviceName = connectedPeripheral?.name ?? "Glasses"
        if let connectedPeripheral {
            discoveredDevices.removeAll { $0.peripheral.identifier == connectedPeripheral.identifier }
        }
        statusMessage = "Connected to \(connectedDeviceName)"
        getDeviceInfo()
        getBattery()
        getMediaInfo()
        raiseGlassesVolumeForPlayback()
    }
}

// MARK: - CBCentralManagerDelegate
extension HeyCyanService: CBCentralManagerDelegate {
    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor in
            switch central.state {
            case .poweredOn:
                if deviceState != .connected && deviceState != .connecting {
                    statusMessage = "Bluetooth is on"
                }
                autoConnectIfNeeded()
            case .poweredOff:
                statusMessage = "Bluetooth is off"
                deviceState = .unknown
            case .unauthorized:
                statusMessage = "Bluetooth permission not granted"
            case .unsupported:
                statusMessage = "Bluetooth is not supported on this device"
            case .resetting:
                statusMessage = "Bluetooth is resetting"
            case .unknown:
                statusMessage = "Bluetooth state is unknown"
            @unknown default:
                statusMessage = "Unexpected Bluetooth state"
            }
        }
    }
}

// MARK: - QCCentralManagerDelegate
extension HeyCyanService: QCCentralManagerDelegate {

    // Devices discovered
    nonisolated func didScanPeripherals(_ peripheralArr: [QCBlePeripheral]) {
        Task { @MainActor in
            isScanning = false

            let sdkConnectedID: UUID?
            if QCCentralManager.shared().deviceState == .connected, let sdkConnectedPeripheral {
                sdkConnectedID = sdkConnectedPeripheral.identifier
            } else {
                sdkConnectedID = nil
            }
            let connectedID = connectedPeripheral?.identifier ?? sdkConnectedID
            discoveredDevices = peripheralArr.filter { device in
                guard isLikelyGlasses(device) || device.isPaired else { return false }
                guard let connectedID else { return true }
                return device.peripheral.identifier != connectedID
            }

            if autoConnectOnNextScan, let device = preferredAutoConnectDevice(from: peripheralArr) {
                autoConnectOnNextScan = false
                let name = device.peripheral.name ?? "Glasses"
                statusMessage = "Found \(name). Connecting..."
                connect(device)
            } else if peripheralArr.isEmpty {
                statusMessage = "No M02_9440 glasses found. Check that the glasses are advertising or in pairing mode"
            } else {
                autoConnectOnNextScan = false
                let names = peripheralArr.compactMap { $0.peripheral.name }.prefix(3).joined(separator: ", ")
                statusMessage = names.isEmpty ? "Found \(peripheralArr.count) devices" : "Devices found: \(names)"
            }
        }
    }

    // Device state changes
    nonisolated func didState(_ state: QCState) {
        Task { @MainActor in
            switch state {
            case .unbind:
                if deviceState != .connected && deviceState != .connecting {
                    deviceState = .unbind
                    statusMessage = "No paired device"
                }
            case .connecting:
                deviceState = .connecting
                statusMessage = "Connecting..."
            case .connected:
                applyConnectedState(peripheral: sdkConnectedPeripheral)
            case .disconnecting:
                deviceState = .disconnecting
            case .disconnected:
                deviceState = .disconnected
                statusMessage = "Disconnected"
                stopLivePreview()
            case .unkown:
                deviceState = .unknown
            @unknown default:
                break
            }
        }
    }

    // Bluetooth state
    nonisolated func didBluetoothState(_ state: QCBluetoothState) {
        print("Bluetooth state: \(state)")
        Task { @MainActor in
            switch state {
            case .poweredOn:
                autoConnectIfNeeded()
            case .poweredOff:
                deviceState = .unknown
                statusMessage = "Bluetooth is off"
            default:
                break
            }
        }
    }

    // Connection succeeded
    nonisolated func didConnected(_ peripheral: CBPeripheral!) {
        Task { @MainActor in
            applyConnectedState(peripheral: peripheral)
            print("[HeyCyan] Connected: \(peripheral.name ?? "Unknown device")")
        }
    }

    // Connection failed
    nonisolated func didFailConnected(_ peripheral: CBPeripheral?, error: Error?) {
        Task { @MainActor in
            deviceState = .unbind
            statusMessage = "Connection failed"
            print("Connection failed: \(error?.localizedDescription ?? "Unknown error")")
        }
    }

    // Disconnect
    nonisolated func didDisconnecte(_ peripheral: CBPeripheral!) {
        Task { @MainActor in
            deviceState = .disconnected
            statusMessage = "Device disconnected"
            stopLivePreview()
        }
    }
}

// MARK: - QCSDKManagerDelegate
extension HeyCyanService: QCSDKManagerDelegate {

    // Media updated
    nonisolated func didUpdateMedia(withPhotoCount photo: Int, videoCount: Int, audioCount: Int, type: Int) {
        Task { @MainActor in
            self.photoCount = photo
            self.videoCount = videoCount
            self.audioCount = audioCount
            print("[HeyCyan] Media updated - Photos: \(photo), Videos: \(videoCount), Audio: \(audioCount)")

            // Use image frames returned directly by the SDK for live preview to avoid thumbnail download latency and extra capture feedback.
            if self.isLivePreviewActive || self.pendingLiveFrameRequest {
                self.isTakingPhoto = false
            } else if photo > 0 {
                self.getLatestThumbnail()
            }
        }
    }

    // Battery updated
    nonisolated func didUpdateBatteryLevel(_ battery: Int, charging: Bool) {
        Task { @MainActor in
            self.batteryLevel = battery
            self.isCharging = charging
        }
    }

    nonisolated func didReceiveAIChatImageData(_ imageData: Data) {
        Task { @MainActor in
            guard let image = UIImage(data: imageData) else {
                self.pendingLiveFrameRequest = false
                self.isTakingPhoto = false
                self.livePreviewError = "The glasses image could not be decoded"
                self.finishPendingFrameCapture(with: nil)
                return
            }

            self.acceptGlassesImage(image, source: "vision frame")
            print("[HeyCyan] Received glasses image: \(imageData.count) bytes")
        }
    }

    nonisolated func didReceiveAIChatVoiceData(_ pcmData: Data) {
        print("[HeyCyan] Received voice data: \(pcmData.count) bytes")
    }

    nonisolated func didReceiveAIChatTextMessage(_ message: String) {
        print("[HeyCyan] Received text: \(message)")
    }
}

#endif
