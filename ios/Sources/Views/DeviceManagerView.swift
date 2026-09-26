//
//  DeviceManagerView.swift
//  LiberEye
//
//  Manage glasses and the vibration band.
//

import SwiftUI
import CoreBluetooth
import UIKit

struct DeviceManagerView: View {
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var speechManager: SpeechManager
    @EnvironmentObject var languageManager: AppLanguageManager
    @Binding var perceptionMode: PerceptionMode

    @StateObject private var heyCyanService = HeyCyanService.shared
    @State private var showVibrationTest = false
    @State private var lastVibrationTestMessage = "Select a level to send a test vibration."

    var body: some View {
        NavigationStack {
            ZStack {
                LGStyle.backgroundGradient.ignoresSafeArea()

                List {
                    // Bluetooth status
                    Section {
                        bluetoothStatusRow
                    }

                    // Connected devices
                    Section(languageManager.text("connected_devices")) {
                        #if LIBEREYE_WITH_HEYCYAN
                        connectedGlassesRow
                        #endif
                        connectedBraceletRow
                    }

                    // Scanned and discovered devices
                    #if LIBEREYE_WITH_HEYCYAN
                    if heyCyanService.isScanning || !heyCyanService.discoveredDevices.isEmpty {
                        Section(languageManager.text("found_heyc_glasses")) {
                            if heyCyanService.isScanning {
                                scanningRow
                            }
                            ForEach(heyCyanService.discoveredDevices, id: \.peripheral.identifier) { device in
                                heyCyanDeviceRow(device)
                            }
                        }
                    }

                    #endif

                    if bluetoothManager.isScanning || !bluetoothManager.discoveredDevices.isEmpty {
                        Section(languageManager.text("found_bracelets")) {
                            if bluetoothManager.isScanning {
                                scanningRow
                            }
                            ForEach(bluetoothManager.discoveredDevices, id: \.identifier) { peripheral in
                                discoveredDeviceRow(peripheral)
                            }
                        }
                    }

                    // Vibration test
                    Section(languageManager.text("bracelet_vibration_test")) {
                        vibrationTestStatusRow
                        ForEach(DangerLevel.allCases, id: \.rawValue) { level in
                            if level != .safe {
                                vibrationTestRow(level)
                            }
                        }
                        vibrationCommandTestRow(title: "W1 Hazard attention", description: "Two strong 0.25 s pulses", command: .hazardAttention, color: .orange)
                        vibrationCommandTestRow(title: "W2 Immediate avoidance", description: "Three strong pulses, a pause, then three strong pulses", command: .immediateAvoidance, color: .red)
                        vibrationCommandTestRow(title: "W3 Emergency stop", description: "One strong 1 s pulse, then four rapid short pulses", command: .emergencyStop, color: Color(red: 0.8, green: 0, blue: 0))
                    }

                    // Perception mode
                    Section(languageManager.text("perception_mode")) {
                        perceptionModeRow
                    }
                }
                .liquidGlassSystemList()
                .safeAreaInset(edge: .bottom) {
                    Color.clear.frame(height: LGStyle.tabBarAvoidanceHeight)
                }
            }
            .navigationTitle(languageManager.text("device_manager"))
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: {
                        if heyCyanService.isScanning || bluetoothManager.isScanning {
                            heyCyanService.stopScanning()
                            bluetoothManager.stopScanning()
                        } else {
                            #if LIBEREYE_WITH_HEYCYAN
                            heyCyanService.startScanning()
                            #endif
                            bluetoothManager.scanForBracelet()
                        }
                    }) {
                        if heyCyanService.isScanning || bluetoothManager.isScanning {
                            Label(languageManager.text("stop_scanning"), systemImage: "stop.circle")
                        } else {
                            Label(languageManager.text("scan_devices"), systemImage: "antenna.radiowaves.left.and.right")
                        }
                    }
                    .disabled(!bluetoothManager.bluetoothAvailable)
                }
            }
        }
        .onAppear {
            guard !AppRuntime.isRunningForPreviews else { return }
            heyCyanService.refreshConnectionStatus(autoConnect: true)
            bluetoothManager.autoConnectBraceletIfNeeded()
        }
    }

    // MARK: - Bluetooth status row
    private var bluetoothStatusRow: some View {
        HStack {
            Image(systemName: bluetoothManager.bluetoothAvailable ? "wave.3.right" : "exclamationmark.icloud")
                .foregroundColor(bluetoothManager.bluetoothAvailable ? .blue : .red)
                .font(.title2)

            VStack(alignment: .leading, spacing: 2) {
                Text(bluetoothManager.bluetoothAvailable ? languageManager.text("bluetooth_enabled") : languageManager.text("bluetooth_disabled"))
                    .font(.headline)
                Text(localizedBluetoothStatus)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            if bluetoothManager.bluetoothAvailable {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green)
            }
        }
        .padding(.vertical, 4)
        .accessibilityLabel("\(languageManager.text("band_scan_status")): \(localizedBluetoothStatus)")
    }

    // MARK: - Glasses row
    private var connectedGlassesRow: some View {
        HStack {
            Image(systemName: "eyeglasses")
                .font(.title2)
                .foregroundColor(.blue)
                .frame(width: 36)

            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.text("glasses"))
                    .font(.headline)
                HStack(spacing: 4) {
                    Circle()
                        .fill(heyCyanService.deviceState == .connected ? .green : (heyCyanService.deviceState == .connecting ? .orange : .gray))
                        .frame(width: 8, height: 8)
                    Text(heyCyanService.deviceState.displayText)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
            }

            Spacer()

            if heyCyanService.deviceState == .connected {
                Button(action: {
                    heyCyanService.disconnect()
                }) {
                    Text(languageManager.text("disconnect"))
                        .font(.subheadline)
                        .foregroundColor(.red)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
        .accessibilityLabel("Glasses, \(heyCyanService.deviceState.displayText)")
    }

    // MARK: - Vibration band row
    private var connectedBraceletRow: some View {
        HStack {
            Image(systemName: "applewatch")
                .font(.title2)
                .foregroundColor(.teal)
                .frame(width: 36)

            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.text("vibration_bracelet"))
                    .font(.headline)
                HStack(spacing: 4) {
                    Circle()
                        .fill(bluetoothManager.braceletState.color)
                        .frame(width: 8, height: 8)
                    Text(braceletStatusText)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
            }

            Spacer()

            if bluetoothManager.braceletState == .connected {
                Button(action: {
                    bluetoothManager.disconnectBracelet()
                }) {
                    Text(languageManager.text("disconnect"))
                        .font(.subheadline)
                        .foregroundColor(.red)
                }
                .buttonStyle(.plain)
            } else if bluetoothManager.braceletState != .connecting {
                Button(action: {
                    bluetoothManager.scanForBracelet()
                }) {
                    Text(languageManager.text("connect_band"))
                        .font(.subheadline)
                        .foregroundColor(.blue)
                }
                .buttonStyle(.plain)
            } else {
                ProgressView()
            }
        }
        .padding(.vertical, 4)
        .accessibilityLabel("Vibration band, \(bluetoothManager.braceletState.displayText)")
    }

    private var braceletStatusText: String {
        if bluetoothManager.braceletState == .connected {
            let name = bluetoothManager.braceletDeviceName.isEmpty ? BluetoothUUIDs.braceletDisplayName : bluetoothManager.braceletDeviceName
            return bluetoothManager.braceletControlReady
            ? languageManager.format("connected_name", name)
            : languageManager.format("connected_finding_vibration", name)
        }
        return bluetoothManager.braceletState.displayText
    }

    private var localizedBluetoothStatus: String {
        bluetoothManager.statusMessage
    }

    // MARK: - Scanning row
    private var scanningRow: some View {
        HStack {
            ProgressView()
                .scaleEffect(0.8)
            Text(languageManager.text("scanning_nearby"))
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
    }

    // MARK: - Discovered device row
    private func discoveredDeviceRow(_ peripheral: CBPeripheral) -> some View {
        Button(action: {
            bluetoothManager.connect(peripheral: peripheral)
        }) {
            HStack {
                Image(systemName: "applewatch")
                    .foregroundColor(.teal)
                    .frame(width: 36)

                VStack(alignment: .leading, spacing: 2) {
                    Text(peripheral.name ?? languageManager.text("unknown_device"))
                        .font(.headline)
                        .foregroundColor(.primary)
                    Text(languageManager.text("tap_connect_band"))
                        .font(.caption)
                        .foregroundColor(.blue)
                }

                Spacer()

                Image(systemName: "plus.circle.fill")
                    .foregroundColor(.blue)
            }
        }
        .accessibilityLabel("Found device \(peripheral.name ?? "Unknown device"). Tap to connect.")
    }

    private func heyCyanDeviceRow(_ device: GlassesDiscoveredDevice) -> some View {
        let peripheral = device.peripheral
        return Button(action: {
            heyCyanService.connect(device)
        }) {
            HStack {
                Image(systemName: "eyeglasses")
                    .foregroundColor(.blue)
                    .frame(width: 36)

                VStack(alignment: .leading, spacing: 2) {
                    Text(peripheral.name ?? languageManager.text("unknown_glasses"))
                        .font(.headline)
                        .foregroundColor(.primary)
                    Text(device.mac.isEmpty ? languageManager.text("tap_to_connect") : device.mac)
                        .font(.caption)
                        .foregroundColor(.blue)
                }

                Spacer()

                if heyCyanService.deviceState == .connecting {
                    ProgressView()
                } else {
                    Image(systemName: "plus.circle.fill")
                        .foregroundColor(.blue)
                }
            }
        }
        .accessibilityLabel("Found HeyCyan glasses \(peripheral.name ?? "Unknown device"). Tap to connect.")
    }

    // MARK: - Vibration test row
    private var vibrationTestStatusRow: some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(bluetoothManager.braceletControlReady ? "Band vibration service ready" : "Connect the band and wait for its vibration service.",
                  systemImage: bluetoothManager.braceletControlReady ? "checkmark.circle.fill" : "exclamationmark.circle")
                .font(.subheadline)
                .foregroundColor(bluetoothManager.braceletControlReady ? .green : .orange)
            Text(lastVibrationTestMessage)
                .font(.caption)
                .foregroundColor(.secondary)
            Text(bluetoothManager.statusMessage)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 6)
    }

    private func vibrationTestRow(_ level: DangerLevel) -> some View {
        let isReady = bluetoothManager.braceletState == .connected && bluetoothManager.braceletControlReady

        return HStack(spacing: 14) {
            Circle()
                .fill(level.color)
                .frame(width: 14, height: 14)

            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.format("level_vibration", level.displayText))
                    .font(.headline)
                    .foregroundColor(.primary)
                Text(level.vibrationDescription)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            Button(action: {
                UIImpactFeedbackGenerator(style: .medium).impactOccurred()
                let command = VibrationCommand.from(dangerLevel: level)
                bluetoothManager.sendVibration(command)
                lastVibrationTestMessage = "Sending \(level.displayText) vibration to \(BluetoothUUIDs.braceletDisplayName)."
                speechManager.speak("Testing \(level.displayText) vibration: \(level.vibrationDescription)", priority: .normal)
            }) {
                Label("Test", systemImage: "waveform.path")
                    .font(.subheadline.weight(.semibold))
                    .labelStyle(.titleAndIcon)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .foregroundColor(.white)
                    .background(Capsule().fill(isReady ? level.color : Color.gray))
            }
            .buttonStyle(.plain)
            .disabled(!isReady)
        }
        .contentShape(Rectangle())
        .padding(.vertical, 8)
        .opacity(isReady ? 1 : 0.45)
        .accessibilityLabel("Test \(level.displayText) vibration")
    }

    private func vibrationCommandTestRow(title: String, description: String, command: VibrationCommand, color: Color) -> some View {
        let isReady = bluetoothManager.braceletState == .connected && bluetoothManager.braceletControlReady

        return HStack(spacing: 14) {
            Circle()
                .fill(color)
                .frame(width: 14, height: 14)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                    .foregroundColor(.primary)
                Text(description)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            Button(action: {
                UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
                bluetoothManager.sendVibration(command)
                lastVibrationTestMessage = "Sending \(title) to \(BluetoothUUIDs.braceletDisplayName)."
                speechManager.speak("Testing \(title): \(description)", priority: .normal)
            }) {
                Label("Test", systemImage: "waveform.path.ecg")
                    .font(.subheadline.weight(.semibold))
                    .labelStyle(.titleAndIcon)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .foregroundColor(.white)
                    .background(Capsule().fill(isReady ? color : Color.gray))
            }
            .buttonStyle(.plain)
            .disabled(!isReady)
        }
        .contentShape(Rectangle())
        .padding(.vertical, 8)
        .opacity(isReady ? 1 : 0.45)
        .accessibilityLabel("Test \(title)")
    }

    // MARK: - Perception mode row
    private var perceptionModeRow: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(languageManager.text("current_mode"))
                .font(.subheadline)
                .foregroundColor(.secondary)

            HStack(spacing: 10) {
                ForEach(PerceptionMode.availableModes, id: \.self) { mode in
                    Button(action: {
                        if mode == .glasses && heyCyanService.deviceState != .connected {
                            speechManager.speak("Connect the glasses first.")
                            return
                        }
                        withAnimation { perceptionMode = mode }
                        speechManager.speak("Switched to \(mode.displayName) mode.")
                    }) {
                        HStack {
                            Image(systemName: mode.icon)
                            Text(mode.displayName)
                                .font(.subheadline)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 8)
                        .background(
                            Capsule()
                                .fill(perceptionMode == mode ? Color.blue : Color(uiColor: .secondarySystemBackground))
                        )
                        .foregroundColor(perceptionMode == mode ? .white : .primary)
                    }
                    .buttonStyle(.plain)
                    .opacity(mode == .glasses && heyCyanService.deviceState != .connected ? 0.4 : 1)
                }
            }

            #if !LIBEREYE_WITH_HEYCYAN
            Text(languageManager.text("glasses_unavailable_note"))
                .font(.caption)
                .foregroundColor(.secondary)
            #endif

            Text(perceptionMode == .glasses
                 ? languageManager.text("glasses_mode_note")
                 : languageManager.text("phone_mode_note"))
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - DangerLevel CaseIterable
extension DangerLevel: CaseIterable {
    static var allCases: [DangerLevel] {
        [.safe, .low, .medium, .high, .critical]
    }
}
