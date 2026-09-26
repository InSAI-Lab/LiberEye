//
//  MainTabView.swift
//  LiberEye
//
//  Main tab view and application navigation.
//

import SwiftUI

struct MainTabView: View {
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var locationManager: LocationManager
    @EnvironmentObject var visionService: VisionService
    @EnvironmentObject var cameraManager: CameraManager
    @EnvironmentObject var speechManager: SpeechManager
    @AppStorage("auto_obstacle_voice") private var autoObstacleVoice: Bool = true
    @AppStorage("obstacle_voice_threshold") private var obstacleVoiceThreshold: Int = 1

    @StateObject private var heyCyanService = HeyCyanService.shared
    @State private var selectedTab: AppFeature = .obstacle
    @State private var perceptionMode: PerceptionMode = .phone

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .bottom) {
                // Main content
                TabView(selection: $selectedTab) {
                    ObstacleView(perceptionMode: $perceptionMode)
                        .tag(AppFeature.obstacle)

                    NavigationLocationView()
                        .tag(AppFeature.navigation)

                    SceneAnalysisView()
                        .tag(AppFeature.sceneAnalysis)

                    DeviceManagerView(perceptionMode: $perceptionMode)
                        .tag(AppFeature.deviceManager)

                    SettingsView()
                        .tag(AppFeature.settings)
                }

                // Custom bottom navigation with larger touch targets.
                CustomTabBar(selectedTab: $selectedTab, bottomInset: proxy.safeAreaInsets.bottom)
            }
        }
        .ignoresSafeArea(.keyboard)
        .onAppear {
            guard !AppRuntime.isRunningForPreviews else { return }
            locationManager.requestPermissionAndStart()
            heyCyanService.refreshConnectionStatus(autoConnect: true)
            if heyCyanService.deviceState == .connected {
                perceptionMode = .glasses
                cameraManager.stopSession()
            }
        }
        // Update perception mode when HeyCyan glasses connect or disconnect.
        .onChange(of: heyCyanService.deviceState) { _, newState in
            if newState == .connected {
                perceptionMode = .glasses
                cameraManager.stopSession()
                speechManager.speak("Glasses connected. Switched to glasses mode.", priority: .high)
            } else if (newState == .disconnected || newState == .unbind) && perceptionMode == .glasses {
                perceptionMode = .phone
                speechManager.speak("Glasses disconnected. Switched to phone camera mode.", priority: .high)
            }
        }
        // Announce obstacle updates.
        .onChange(of: bluetoothManager.latestObstacle) { _, newObstacle in
            if let obstacle = newObstacle,
               !LiberEyeCloudConfig.isEnabled,
               autoObstacleVoice,
               obstacle.dangerLevel != .safe,
               obstacle.dangerLevel.rawValue >= obstacleVoiceThreshold {
                speechManager.speakObstacleAlert(obstacle)
            }
        }
    }
}

// MARK: - Custom bottom navigation
struct CustomTabBar: View {
    @Binding var selectedTab: AppFeature
    let bottomInset: CGFloat
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var languageManager: AppLanguageManager
    @StateObject private var heyCyanService = HeyCyanService.shared

    // Primary feature navigation
    private let tabs: [AppFeature] = [.obstacle, .navigation, .sceneAnalysis, .deviceManager, .settings]

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                ForEach(tabs, id: \.self) { tab in
                    TabBarButton(
                        feature: tab,
                        isSelected: selectedTab == tab,
                        badge: badgeForTab(tab)
                    ) {
                        selectedTab = tab
                    }
                }
            }
            .frame(height: 86)
            .padding(.horizontal, 8)
            .padding(.top, 8)

            Color.clear
                .frame(height: max(bottomInset, 8))
        }
        .frame(maxWidth: .infinity)
        .background(
            UnevenRoundedRectangle(topLeadingRadius: 18, topTrailingRadius: 18)
                .fill(.ultraThinMaterial)
                .overlay(
                    UnevenRoundedRectangle(topLeadingRadius: 18, topTrailingRadius: 18)
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color.white.opacity(0.46),
                                    Color.white.opacity(0.20),
                                    Color.white.opacity(0.08)
                                ],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                )
                .overlay(
                    UnevenRoundedRectangle(topLeadingRadius: 18, topTrailingRadius: 18)
                        .stroke(
                            Color.white.opacity(0.55),
                            lineWidth: 1.2
                        )
                )
                .shadow(color: .black.opacity(0.10), radius: 16, y: -5)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private func badgeForTab(_ tab: AppFeature) -> String? {
        switch tab {
        case .obstacle:
            if bluetoothManager.currentDangerLevel >= .medium {
                return "!"
            }
            return nil
        case .deviceManager:
            let connected = (heyCyanService.deviceState == .connected ? 1 : 0) +
                           (bluetoothManager.braceletState == .connected ? 1 : 0)
            return connected > 0 ? "\(connected)" : nil
        default:
            return nil
        }
    }
}

struct TabBarButton: View {
    let feature: AppFeature
    let isSelected: Bool
    let badge: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 7) {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: feature.icon)
                        .font(.system(size: 30, weight: isSelected ? .semibold : .medium))
                        .foregroundColor(isSelected ? feature.color : .gray)

                    if let badge = badge {
                        Text(badge)
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(.white)
                            .padding(3)
                            .background(Circle().fill(Color.red))
                            .offset(x: 8, y: -8)
                    }
                }

                Text(feature.displayTitle)
                    .font(.system(size: 13, weight: isSelected ? .semibold : .medium))
                    .foregroundColor(isSelected ? feature.color : .gray)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 78, alignment: .bottom)
            .padding(.top, 8)
            .padding(.bottom, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(isSelected ? "Selected, \(feature.accessibilityLabel)" : feature.accessibilityLabel)
        .accessibilityHint("Double-tap to open \(feature.displayTitle)")
    }
}

#Preview("LiberEye main view") {
    MainTabView()
        .environmentObject(AuthManager.shared)
        .environmentObject(BluetoothManager())
        .environmentObject(LocationManager())
        .environmentObject(VisionService())
        .environmentObject(CameraManager())
        .environmentObject(SpeechManager())
        .environmentObject(VoiceAssistantManager())
        .environmentObject(AppLanguageManager.shared)
}
