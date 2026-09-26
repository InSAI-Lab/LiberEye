//
//  BluetoothManager.swift
//  LiberEye
//
//  Bluetooth connections for glasses and the haptic wristband
//

import Foundation
import CoreBluetooth
import Combine
import SwiftUI

// MARK: - Bluetooth service UUIDs
// Glasses adapters must use the UUIDs implemented by their device firmware.
nonisolated enum BluetoothUUIDs {
    // Glasses service
    static let glassesService = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    static let glassesObstacleTX = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E") // Obstacle notifications from glasses
    static let glassesControlRX = CBUUID(string: "6E400002-B5A3-F393-E0A9-E50E24DCCA9E") // Control commands

    // The LiberEye wrist firmware uses Nordic UART Service through Arduino BLEUart.
    static let braceletService = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
    static let braceletVibrationRX = CBUUID(string: "6E400002-B5A3-F393-E0A9-E50E24DCCA9E") // Haptic commands written by the phone
    static let braceletStatusTX = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")   // Wristband status notifications
    static let braceletCandidateServices = [braceletService]

    // Device discovery name filters
    static let glassesNameKeywords = ["LiberEye-Glass", "M02", "HeyCyan", "QC", "Glass"]
    static let braceletDisplayName = "LiberEye-Haptic"
    static let braceletNameKeywords = [braceletDisplayName, "LiberEye-Haptic"]
}

// MARK: - Obstacle packets received from glasses
nonisolated struct ObstacleDataPacket {
    let direction: Int     // 0=front, 1=front left, 2=front right, 3=left, 4=right
    let distance: Double   // Distance in meters
    let objectType: Int    // Object type code

    nonisolated static func parse(from data: Data) -> ObstacleDataPacket? {
        guard data.count >= 6 else { return nil }
        let direction = Int(data[0])
        let distanceRaw = UInt16(data[1]) | (UInt16(data[2]) << 8)
        let distance = Double(distanceRaw) / 100.0  // cm -> m
        let objectType = Int(data[3])
        return ObstacleDataPacket(direction: direction, distance: distance, objectType: objectType)
    }

    var directionText: String {
        switch direction {
        case 0: return "ahead"
        case 1: return "ahead on the left"
        case 2: return "ahead on the right"
        case 3: return "on the left"
        case 4: return "on the right"
        default: return "ahead"
        }
    }

    var objectDescription: String {
        switch objectType {
        case 0: return "an obstacle"
        case 1: return "a pedestrian"
        case 2: return "a vehicle"
        case 3: return "a step"
        case 4: return "a door"
        case 5: return "a wall"
        case 6: return "a pothole"
        default: return "an unidentified obstacle"
        }
    }

    var dangerLevel: DangerLevel {
        switch distance {
        case 0..<0.8: return .critical
        case 0.8..<1.5: return .high
        case 1.5..<3.0: return .medium
        case 3.0..<5.0: return .low
        default: return .safe
        }
    }
}

extension VibrationCommand {
    static func from(dangerLevel: DangerLevel) -> VibrationCommand {
        switch dangerLevel {
        case .safe:
            return VibrationCommand(pattern: .stop, duration: 0)
        case .low:
            return VibrationCommand(pattern: .d1, duration: 5000)
        case .medium:
            return VibrationCommand(pattern: .d2, duration: 5000)
        case .high:
            return VibrationCommand(pattern: .d3, duration: 3000)
        case .critical:
            return VibrationCommand(pattern: .d4, duration: 2000)
        }
    }

}

// MARK: - Bluetooth manager
@MainActor
class BluetoothManager: NSObject, ObservableObject {

    // MARK: - Published state
    @Published var glassesState: DeviceConnectionState = .disconnected
    @Published var braceletState: DeviceConnectionState = .disconnected
    @Published var isScanning: Bool = false
    @Published var discoveredDevices: [CBPeripheral] = []
    @Published var latestObstacle: ObstacleInfo? = nil
    @Published var currentDangerLevel: DangerLevel = .safe
    @Published var lastObstacleUpdateAt: Date? = nil
    @Published var bluetoothAvailable: Bool = false
    @Published var statusMessage: String = "Bluetooth is not initialized"
    @Published var braceletDeviceName: String = ""
    @Published var braceletControlReady: Bool = false
    @Published private(set) var lastBraceletAcknowledgement: String?
    @Published private(set) var braceletCommandPending = false

    var canDeliverFeedback: Bool {
        braceletState == .connected && braceletControlReady
            && (UserDefaults.standard.object(forKey: "vibration_enabled") as? Bool ?? true)
    }

    // MARK: - Private state
    private var centralManager: CBCentralManager!
    private var glassesPeripheral: CBPeripheral?
    private var braceletPeripheral: CBPeripheral?

    private var glassesObstacleTXCharacteristic: CBCharacteristic?
    private var glassesControlRXCharacteristic: CBCharacteristic?
    private var braceletVibrationRXCharacteristic: CBCharacteristic?
    private var braceletStatusTXCharacteristic: CBCharacteristic?
    private var pendingCommandCode: UInt8?
    private var acknowledgementTask: Task<Void, Never>?
    private var statusDecoder = WristStatusDecoder()

    private var vibrationTimer: Timer?
    private var lastVibrationLevel: DangerLevel = .safe
    private var didRequestInitialAutoConnect = false

    // MARK: - Initialization
    override init() {
        super.init()
        guard !AppRuntime.isRunningForPreviews else {
            statusMessage = "Preview mode"
            return
        }
        centralManager = CBCentralManager(delegate: self, queue: nil)
    }

    func autoConnectBraceletIfNeeded() {
        guard !AppRuntime.isRunningForPreviews else { return }
        guard !didRequestInitialAutoConnect else { return }
        guard centralManager.state == .poweredOn else { return }
        didRequestInitialAutoConnect = true
        if connectRetrievedBraceletIfAvailable() {
            return
        }
        startScanning(autoConnectBracelet: true)
    }

    func scanForBracelet() {
        guard !AppRuntime.isRunningForPreviews else { return }
        resetBraceletState()
        discoveredDevices.removeAll()
        if connectRetrievedBraceletIfAvailable() {
            return
        }
        startScanning(autoConnectBracelet: true)
    }

    // MARK: - Device discovery
    func startScanning(autoConnectBracelet: Bool = false) {
        guard !AppRuntime.isRunningForPreviews else { return }
        guard centralManager.state == .poweredOn else {
            statusMessage = "Turn on Bluetooth"
            return
        }
        isScanning = true
        if !autoConnectBracelet {
            discoveredDevices.removeAll()
        }
        statusMessage = autoConnectBracelet ? "Looking for the \(BluetoothUUIDs.braceletDisplayName) wristband..." : "Scanning for wristbands..."
        centralManager.scanForPeripherals(
            withServices: nil,
            options: [CBCentralManagerScanOptionAllowDuplicatesKey: true]
        )
        // Stop after the discovery timeout.
        DispatchQueue.main.asyncAfter(deadline: .now() + (autoConnectBracelet ? 20 : 15)) { [weak self] in
            guard let self else { return }
            if self.isScanning {
                self.stopScanning()
            }
        }
    }

    func stopScanning() {
        guard !AppRuntime.isRunningForPreviews else { return }
        centralManager.stopScan()
        isScanning = false
        if discoveredDevices.isEmpty {
            statusMessage = braceletState == .connected
                ? "Haptic wristband connected"
                : "No \(BluetoothUUIDs.braceletDisplayName) wristband found. If paired in system Bluetooth settings, disconnect or forget it there, then reconnect in the app."
        }
    }

    // MARK: - Device connection
    func connect(peripheral: CBPeripheral) {
        guard !AppRuntime.isRunningForPreviews else { return }
        centralManager.stopScan()
        isScanning = false

        let name = peripheral.name ?? ""
        guard isBraceletName(name) else {
            statusMessage = "Select the \(BluetoothUUIDs.braceletDisplayName) haptic wristband"
            return
        }

        braceletState = .connecting
        braceletPeripheral = peripheral
        braceletDeviceName = name
        braceletControlReady = false

        peripheral.delegate = self
        centralManager.connect(peripheral, options: nil)
        statusMessage = "Connecting to \(name)..."
    }

    // MARK: - Device disconnection
    func disconnectGlasses() {
        guard !AppRuntime.isRunningForPreviews else { return }
        if let peripheral = glassesPeripheral {
            centralManager.cancelPeripheralConnection(peripheral)
        }
    }

    func disconnectBracelet() {
        stopVibration()
        guard !AppRuntime.isRunningForPreviews else { return }
        if let peripheral = braceletPeripheral {
            centralManager.cancelPeripheralConnection(peripheral)
        }
        braceletControlReady = false
    }

    // MARK: - Sending haptic commands
    func sendVibration(_ command: VibrationCommand) {
        guard command.pattern == .stop || (UserDefaults.standard.object(forKey: "vibration_enabled") as? Bool ?? true) else { return }
        guard braceletState == .connected else {
            statusMessage = "Connect the \(BluetoothUUIDs.braceletDisplayName) wristband first"
            return
        }

        guard let characteristic = braceletVibrationRXCharacteristic,
              let peripheral = braceletPeripheral else {
            statusMessage = "The wristband is connected, but its haptic control characteristic is missing"
            return
        }

        guard braceletControlReady else {
            statusMessage = "Waiting for wristband NUS control and status services"
            return
        }
        let startsAcknowledgementWindow = !braceletCommandPending
        pendingCommandCode = command.pattern.rawValue
        braceletCommandPending = true
        if startsAcknowledgementWindow {
            acknowledgementTask?.cancel()
            acknowledgementTask = Task { @MainActor [weak self] in
                do { try await Task.sleep(nanoseconds: 2_000_000_000) } catch { return }
                guard let self, self.braceletCommandPending else { return }
                self.braceletCommandPending = false
                self.pendingCommandCode = nil
                self.braceletControlReady = false
                self.statusMessage = "The wristband did not acknowledge the command. Reconnect it."
            }
        }
        // Replacing an unacknowledged command never extends its watchdog window.
        let data = command.toData()
        let writeType: CBCharacteristicWriteType = characteristic.properties.contains(.write) ? .withResponse : .withoutResponse
        peripheral.writeValue(data, for: characteristic, type: writeType)
        statusMessage = "Haptic command sent: \(command.pattern.code)"
    }

    // MARK: - Updating wrist haptics from danger levels
    func updateVibrationForDanger(_ level: DangerLevel, force: Bool = false) {
        guard force || level != lastVibrationLevel else { return }
        lastVibrationLevel = level
        currentDangerLevel = level

        vibrationTimer?.invalidate()
        vibrationTimer = nil

        if level == .safe {
            sendVibration(VibrationCommand(pattern: .stop, duration: 0))
            return
        }

        let command = VibrationCommand.from(dangerLevel: level)
        sendVibration(command)

        // Firmware owns pattern timing and the command lease. Do not restart its waveform from a phone timer.
    }

    func stopVibration() {
        vibrationTimer?.invalidate()
        vibrationTimer = nil
        lastVibrationLevel = .safe
        currentDangerLevel = .safe
        guard braceletState == .connected && braceletControlReady else { return }
        sendVibration(VibrationCommand(pattern: .stop, duration: 0))
    }

    private func resetBraceletState() {
        vibrationTimer?.invalidate()
        vibrationTimer = nil
        acknowledgementTask?.cancel()
        pendingCommandCode = nil
        braceletCommandPending = false
        braceletVibrationRXCharacteristic = nil
        braceletStatusTXCharacteristic = nil
        braceletControlReady = false
        statusDecoder = WristStatusDecoder()
    }

    private func receiveBraceletStatus(_ data: Data) {
        for message in statusDecoder.append(data) {
            switch message.kind {
            case .acknowledgement:
                guard message.code == pendingCommandCode || message.code == 255 else { continue }
                acknowledgementTask?.cancel()
                pendingCommandCode = nil
                braceletCommandPending = false
                lastBraceletAcknowledgement = "ACK \(message.code) \(message.status)"
                switch message.status {
                case "ok", "refresh", "stopped":
                    statusMessage = "Wristband acknowledgement: \(message.status)"
                case "busy":
                    statusMessage = "The wristband is completing a higher-priority warning"
                default:
                    braceletControlReady = false
                    statusMessage = "Wristband rejected the command: \(message.status). Check the firmware and driver."
                }
            case .event:
                if message.status == "driver" {
                    braceletControlReady = false
                    statusMessage = "Wristband driver failure. Check the hardware and reconnect."
                } else if message.status == "ready" && !braceletControlReady {
                    statusMessage = "The wristband driver has recovered. Reconnect it."
                } else {
                    statusMessage = "Wristband status: \(message.status)"
                }
            }
        }
    }

    // MARK: - Navigation haptic cues
    func sendNavigationVibration() {
        sendVibration(VibrationCommand.navigationTurn)
    }

    func sendArrivalVibration() {
        sendVibration(VibrationCommand.arrived)
    }

    // MARK: - Simulated glasses data for development
    func simulateObstacleData(direction: Int, distance: Double, objectType: Int) {
        let packet = ObstacleDataPacket(direction: direction, distance: distance, objectType: objectType)
        processObstaclePacket(packet)
    }

    // MARK: - Processing obstacle packets
    private func processObstaclePacket(_ packet: ObstacleDataPacket) {
        lastObstacleUpdateAt = Date()
        let obstacle = ObstacleInfo(
            direction: packet.directionText,
            distance: packet.distance,
            description: packet.objectDescription,
            dangerLevel: packet.dangerLevel,
            timestamp: lastObstacleUpdateAt ?? Date()
        )
        latestObstacle = obstacle
        if !LiberEyeCloudConfig.isEnabled { updateVibrationForDanger(packet.dangerLevel) }
    }

    private func isGlassesName(_ name: String) -> Bool {
        BluetoothUUIDs.glassesNameKeywords.contains { name.localizedCaseInsensitiveContains($0) }
    }

    private func isBraceletName(_ name: String) -> Bool {
        BluetoothUUIDs.braceletNameKeywords.contains { name.localizedCaseInsensitiveContains($0) }
    }

    private func connectRetrievedBraceletIfAvailable() -> Bool {
        guard centralManager.state == .poweredOn else { return false }

        let peripherals = centralManager.retrieveConnectedPeripherals(withServices: BluetoothUUIDs.braceletCandidateServices)
        guard let peripheral = peripherals.first(where: { isBraceletName($0.name ?? "") }) else {
            return false
        }

        centralManager.stopScan()
        isScanning = false
        attachRetrievedBracelet(peripheral)
        return true
    }

    private func attachRetrievedBracelet(_ peripheral: CBPeripheral) {
        braceletPeripheral = peripheral
        braceletDeviceName = peripheral.name ?? BluetoothUUIDs.braceletDisplayName
        braceletControlReady = false
        peripheral.delegate = self
        discoveredDevices.removeAll { $0.identifier == peripheral.identifier }

        if peripheral.state == .connected {
            braceletState = .connected
            statusMessage = "Attached to the system-connected \(braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : braceletDeviceName) wristband. Discovering haptic services..."
            peripheral.discoverServices(nil)
        } else {
            braceletState = .connecting
            statusMessage = "Connecting to the remembered \(braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : braceletDeviceName) wristband..."
            centralManager.connect(peripheral, options: nil)
        }
    }
}

// MARK: - CBCentralManagerDelegate
extension BluetoothManager: CBCentralManagerDelegate {

    nonisolated func centralManagerDidUpdateState(_ central: CBCentralManager) {
        Task { @MainActor in
            switch central.state {
            case .poweredOn:
                bluetoothAvailable = true
                statusMessage = "Bluetooth ready"
                autoConnectBraceletIfNeeded()
            case .poweredOff:
                bluetoothAvailable = false
                glassesState = .disconnected
                braceletState = .disconnected
                resetBraceletState()
                statusMessage = "Turn on Bluetooth"
            case .unauthorized:
                resetBraceletState()
                bluetoothAvailable = false
                statusMessage = "Bluetooth permission denied"
            case .unsupported:
                resetBraceletState()
                bluetoothAvailable = false
                statusMessage = "Bluetooth is not supported on this device"
            default:
                resetBraceletState()
                bluetoothAvailable = false
                statusMessage = "Bluetooth is unavailable"
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager,
                                    didDiscover peripheral: CBPeripheral,
                                    advertisementData: [String: Any],
                                    rssi RSSI: NSNumber) {
        guard let name = peripheral.name else { return }

        Task { @MainActor in
            guard isBraceletName(name) else { return }
            if !discoveredDevices.contains(where: { $0.identifier == peripheral.identifier }) {
                discoveredDevices.append(peripheral)
                statusMessage = "Wristband found: \(name)"
            }
            if isBraceletName(name), braceletState != .connected, braceletState != .connecting {
                connect(peripheral: peripheral)
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        Task { @MainActor in
            let name = peripheral.name ?? ""
            if peripheral.identifier == braceletPeripheral?.identifier {
                braceletState = .connected
                braceletDeviceName = peripheral.name ?? braceletDeviceName
                braceletControlReady = false
                discoveredDevices.removeAll { $0.identifier == peripheral.identifier }
                statusMessage = "\(braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : braceletDeviceName) connected. Discovering haptic services..."
            } else if peripheral.identifier == glassesPeripheral?.identifier {
                glassesState = .connected
                statusMessage = "Glasses connected"
            }
            peripheral.discoverServices(nil)
            _ = name
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager,
                                    didDisconnectPeripheral peripheral: CBPeripheral,
                                    error: Error?) {
        Task { @MainActor in
            if peripheral.identifier == glassesPeripheral?.identifier {
                glassesState = .disconnected
                glassesPeripheral = nil
                glassesObstacleTXCharacteristic = nil
                statusMessage = "Glasses disconnected"
            } else if peripheral.identifier == braceletPeripheral?.identifier {
                braceletState = .disconnected
                braceletPeripheral = nil
                resetBraceletState()
                braceletDeviceName = ""
                statusMessage = "Haptic wristband disconnected"
            }
        }
    }

    nonisolated func centralManager(_ central: CBCentralManager,
                                    didFailToConnect peripheral: CBPeripheral,
                                    error: Error?) {
        Task { @MainActor in
            if peripheral.identifier == glassesPeripheral?.identifier {
                glassesState = .disconnected
            } else {
                braceletState = .disconnected
                braceletControlReady = false
            }
            statusMessage = "Could not connect to \(peripheral.name ?? "wristband"). Try again."
        }
    }
}

// MARK: - CBPeripheralDelegate
extension BluetoothManager: CBPeripheralDelegate {

    nonisolated func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let services = peripheral.services else {
            Task { @MainActor in
                if peripheral.identifier == braceletPeripheral?.identifier {
                    statusMessage = "\(braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : braceletDeviceName) exposes no BLE services. A Bluetooth headset cannot be controlled as a haptic wristband."
                }
            }
            return
        }
        if services.isEmpty {
            Task { @MainActor in
                if peripheral.identifier == braceletPeripheral?.identifier {
                    statusMessage = "No BLE control service found on \(braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : braceletDeviceName). Headset mode cannot receive haptic commands."
                }
            }
            return
        }
        for service in services {
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral,
                                 didDiscoverCharacteristicsFor service: CBService,
                                 error: Error?) {
        guard let characteristics = service.characteristics else { return }

        Task { @MainActor in
            for characteristic in characteristics {
                if peripheral.identifier == braceletPeripheral?.identifier {
                    guard service.uuid == BluetoothUUIDs.braceletService else { continue }
                    if characteristic.uuid == BluetoothUUIDs.braceletVibrationRX,
                       characteristic.properties.contains(.write) || characteristic.properties.contains(.writeWithoutResponse) {
                        braceletVibrationRXCharacteristic = characteristic
                    }
                    if characteristic.uuid == BluetoothUUIDs.braceletStatusTX,
                       characteristic.properties.contains(.notify) {
                        braceletStatusTXCharacteristic = characteristic
                        peripheral.setNotifyValue(true, for: characteristic)
                    }
                    continue
                }
                switch characteristic.uuid {
                case BluetoothUUIDs.glassesObstacleTX:
                    glassesObstacleTXCharacteristic = characteristic
                    peripheral.setNotifyValue(true, for: characteristic)
                case BluetoothUUIDs.glassesControlRX:
                    glassesControlRXCharacteristic = characteristic
                default:
                    break
                }
            }
            if peripheral.identifier == braceletPeripheral?.identifier,
               service.uuid == BluetoothUUIDs.braceletService,
               braceletVibrationRXCharacteristic == nil || braceletStatusTXCharacteristic == nil {
                statusMessage = "The wristband does not expose complete LiberEye NUS control and acknowledgement channels"
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic, error: Error?) {
        Task { @MainActor in
            guard peripheral.identifier == braceletPeripheral?.identifier,
                  characteristic.uuid == BluetoothUUIDs.braceletStatusTX else { return }
            braceletControlReady = error == nil && characteristic.isNotifying && braceletVibrationRXCharacteristic != nil
            statusMessage = braceletControlReady ? "Wristband haptic and acknowledgement channels ready" : "Could not subscribe to wristband status"
            if braceletControlReady { stopVibration() }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral,
                                 didUpdateValueFor characteristic: CBCharacteristic,
                                 error: Error?) {
        guard error == nil, let data = characteristic.value else { return }

        Task { @MainActor in
            if peripheral.identifier == braceletPeripheral?.identifier {
                guard characteristic.uuid == BluetoothUUIDs.braceletStatusTX else { return }
                receiveBraceletStatus(data)
                return
            }

            if characteristic.uuid == BluetoothUUIDs.glassesObstacleTX {
                if let packet = ObstacleDataPacket.parse(from: data) {
                    processObstaclePacket(packet)
                }
            }
        }
    }

    nonisolated func peripheral(_ peripheral: CBPeripheral,
                                 didWriteValueFor characteristic: CBCharacteristic,
                                 error: Error?) {
        Task { @MainActor in
            guard peripheral.identifier == braceletPeripheral?.identifier else { return }
            if let error {
                acknowledgementTask?.cancel()
                pendingCommandCode = nil
                braceletCommandPending = false
                statusMessage = "Could not send the wristband haptic command: \(error.localizedDescription)"
            } else {
                statusMessage = "BLE write complete; waiting for firmware acknowledgement"
            }
        }
    }
}
