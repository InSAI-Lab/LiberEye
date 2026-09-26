//
//  DeviceCameraComponents.swift
//  LiberEye
//

import SwiftUI

extension PerceptionMode {
    static var availableModes: [PerceptionMode] {
        #if LIBEREYE_WITH_HEYCYAN
        return allCases
        #else
        return [.phone]
        #endif
    }
}

// MARK: - HeyCyan glasses status capsule
struct HeyCyanDeviceStatusPill: View {
    @ObservedObject var service: HeyCyanService

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: "eyeglasses")
                .font(.system(size: 12))
            Text(deviceLabel)
                .font(.caption2)
                .fontWeight(.medium)
            Circle()
                .fill(stateColor)
                .frame(width: 7, height: 7)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(
            Capsule()
                .fill(Color(.systemBackground).opacity(0.8))
                .overlay(Capsule().fill(stateColor.opacity(0.08)))
                .overlay(Capsule().stroke(Color.white.opacity(0.5), lineWidth: 1))
        )
        .accessibilityLabel("Glasses, \(service.deviceState.displayText)")
    }

    private var deviceLabel: String {
        if service.deviceState == .connected && !service.connectedDeviceName.isEmpty {
            return service.connectedDeviceName
        }
        return "Glasses"
    }

    private var stateColor: Color {
        switch service.deviceState {
        case .connected: return .green
        case .connecting: return .orange
        case .disconnecting: return .orange
        default: return .gray
        }
    }
}

// MARK: - Glasses camera preview components
struct GlassesCameraPreview: View {
    @ObservedObject var service: HeyCyanService
    @State private var isRecording = false

    var body: some View {
        VStack(spacing: 7) {
            ZStack {
                if service.deviceState == .connected {
                    // Preview for connected glasses
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.black)
                        .frame(height: 286)
                        .overlay {
                            VStack {
                                if let photo = service.latestGlassesPhoto {
                                    // Show a photo or preview frame from the glasses.
                                    Image(uiImage: photo)
                                        .resizable()
                                        .scaledToFill()
                                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                                        .clipShape(RoundedRectangle(cornerRadius: 8))
                                        .overlay(alignment: .bottom) {
                                            HStack(spacing: 16) {
                                                Label("\(service.photoCount)", systemImage: "photo")
                                                Label("\(service.videoCount)", systemImage: "video")
                                            }
                                            .font(.caption2)
                                            .foregroundColor(.white)
                                            .padding(.horizontal, 10)
                                            .padding(.vertical, 5)
                                            .background(Capsule().fill(Color.black.opacity(0.55)))
                                            .padding(.bottom, 8)
                                        }
                                } else if service.isTakingPhoto || service.isDownloading {
                                    // Loading
                                    VStack(spacing: 12) {
                                        ProgressView()
                                            .scaleEffect(1.5)
                                            .tint(.white)
                                        Text(previewLoadingText)
                                            .font(.caption)
                                            .foregroundColor(.white)
                                    }
                                } else {
                                    // Default hint
                                    VStack(spacing: 12) {
                                        Image(systemName: "eyeglasses")
                                            .font(.system(size: 48))
                                            .foregroundColor(.gray)
                                        Text("Tap the photo button below")
                                            .font(.caption)
                                            .foregroundColor(.gray)
                                        Text("to capture the glasses view")
                                            .font(.caption2)
                                            .foregroundColor(.gray.opacity(0.7))

                                        // Media counts
                                        HStack(spacing: 16) {
                                            Label("\(service.photoCount) photos", systemImage: "photo")
                                            Label("\(service.videoCount) videos", systemImage: "video")
                                        }
                                        .font(.caption2)
                                        .foregroundColor(.gray.opacity(0.6))
                                        .padding(.top, 8)
                                    }
                                }
                            }
                            .padding(10)
                        }
                        .overlay(alignment: .topLeading) {
                            Label(service.isLivePreviewActive ? "Live preview" : "Glasses view", systemImage: service.isLivePreviewActive ? "dot.radiowaves.left.and.right" : "eyeglasses")
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundColor(.white)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(Capsule().fill(Color.black.opacity(0.56)))
                                .padding(8)
                        }
                        .overlay(alignment: .topTrailing) {
                            HStack(spacing: 4) {
                                Circle()
                                    .fill(Color.green)
                                    .frame(width: 6, height: 6)
                                Text(service.connectedDeviceName.isEmpty ? "Glasses" : service.connectedDeviceName)
                                    .font(.caption2)
                            }
                            .foregroundColor(.white)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 4)
                            .background(Capsule().fill(Color.black.opacity(0.6)))
                            .padding(8)
                        }
                } else {
                    // Hint when glasses are disconnected
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color(.systemGray6))
                        .frame(height: 160)
                        .overlay {
                            VStack(spacing: 8) {
                                Image(systemName: "eyeglasses")
                                    .font(.system(size: 32))
                                    .foregroundColor(.gray)
                                Text("Connect glasses first")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }
                        }
                }
            }

            // Action buttons
            if service.deviceState == .connected {
                VStack(spacing: 7) {
                    HStack(spacing: 10) {
                        previewControlButton(
                            title: service.isLivePreviewActive ? "Stop live preview" : "Live preview",
                            systemImage: service.isLivePreviewActive ? "pause.circle.fill" : "play.circle.fill",
                            color: service.isLivePreviewActive ? .red : .teal,
                            disabled: service.isTakingPhoto || service.isDownloading,
                            action: toggleLivePreview
                        )

                        previewControlButton(
                            title: "Capture frame",
                            systemImage: "arrow.clockwise",
                            color: .cyan,
                            disabled: service.isTakingPhoto || service.isDownloading,
                            action: refreshFrame
                        )
                    }

                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible()), GridItem(.flexible())], spacing: 7) {
                        previewControlButton(
                            title: "Take photo",
                            systemImage: "camera.fill",
                            color: .blue,
                            disabled: service.isTakingPhoto || service.isDownloading,
                            action: takeGlassesPhoto
                        )

                        previewControlButton(
                            title: "Recognition photo",
                            systemImage: "sparkles",
                            color: .purple,
                            disabled: service.isTakingPhoto || service.isDownloading,
                            action: captureRecognitionPhoto
                        )

                        previewControlButton(
                            title: isRecording ? "Stop recording" : "Record",
                            systemImage: isRecording ? "stop.fill" : "video.fill",
                            color: isRecording ? .red : .orange,
                            disabled: false,
                            action: toggleRecording
                        )

                        previewControlButton(
                            title: "Download",
                            systemImage: "arrow.down.circle",
                            color: .green,
                            disabled: service.isDownloading || service.photoCount == 0,
                            action: downloadMedia
                        )

                        previewControlButton(
                            title: wifiButtonText,
                            systemImage: service.isWifiReady ? "wifi" : "wifi.exclamationmark",
                            color: service.isWifiReady ? .green : .indigo,
                            disabled: service.isPreparingWifi,
                            action: prepareWifi
                        )
                        .gridCellColumns(2)
                    }

                    if !service.wifiSSID.isEmpty && !service.isWifiReady {
                        VStack(alignment: .leading, spacing: 4) {
                            Label(service.wifiSSID, systemImage: "wifi")
                            if !service.wifiPassword.isEmpty {
                                Label(service.wifiPassword, systemImage: "key.fill")
                            }
                        }
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(10)
                        .background(
                            RoundedRectangle(cornerRadius: 8)
                                .fill(Color(.secondarySystemBackground))
                        )
                    }

                }

                // Status message
                Text(previewStatusText)
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            }
        }
    }

    private func takeGlassesPhoto() {
        service.takePhoto()
    }

    private func captureRecognitionPhoto() {
        service.takeAIPhoto()
    }

    private func refreshFrame() {
        Task {
            _ = await service.captureCurrentGlassesFrame()
        }
    }

    private func toggleLivePreview() {
        if service.isLivePreviewActive {
            service.stopLivePreview()
        } else {
            service.startLivePreview()
        }
    }

    private func prepareWifi() {
        if service.isWifiReady {
            service.refreshDeviceWifiIP()
        } else if !service.wifiSSID.isEmpty {
            service.refreshDeviceWifiIP()
        } else {
            service.prepareWifiForMediaTransfer()
        }
    }

    private func toggleRecording() {
        #if LIBEREYE_WITH_HEYCYAN
        if isRecording {
            QCSDKCmdCreator.setDeviceMode(.videoStop, success: {
                isRecording = false
                print("Stop recording")
            }, fail: { _ in
                print("Unable to stop recording")
            })
        } else {
            QCSDKCmdCreator.setDeviceMode(.video, success: {
                isRecording = true
                print("Start recording")
            }, fail: { _ in
                print("Unable to start recording")
            })
        }
        #else
        service.reportUnavailable()
        #endif
    }

    private func downloadMedia() {
        service.downloadAllMedia()
    }

    private func previewControlButton(
        title: String,
        systemImage: String,
        color: Color,
        disabled: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .font(.system(size: 14, weight: .semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .frame(height: 44)
                .background(Capsule().fill(color.opacity(disabled ? 0.48 : 0.94)))
        }
        .buttonStyle(.plain)
        .disabled(disabled)
        .accessibilityLabel(title)
    }

    private var previewLoadingText: String {
        if service.isDownloading {
            return "Downloading... \(Int(service.downloadProgress * 100))%"
        }
        return "Capturing glasses photo..."
    }

    private var previewStatusText: String {
        if let error = service.livePreviewError, !error.isEmpty {
            return error
        }
        if service.isWifiReady, !service.deviceWifiIP.isEmpty {
            return "\(service.statusMessage) \(service.deviceWifiIP)"
        }
        return service.statusMessage
    }

    private var wifiButtonText: String {
        if service.isPreparingWifi {
            return "Connecting to Wi-Fi..."
        }
        if service.isWifiReady {
            return service.deviceWifiIP.isEmpty ? "Wi-Fi ready" : "Wi-Fi \(service.deviceWifiIP)"
        }
        if !service.wifiSSID.isEmpty {
            return "Refresh glasses IP"
        }
        return "Prepare glasses Wi-Fi"
    }
}
