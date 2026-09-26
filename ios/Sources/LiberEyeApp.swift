//
//  LiberEyeApp.swift
//  LiberEye
//
//  Application entry point and shared managers
//

import SwiftUI

@main
struct LiberEyeApp: App {

    @StateObject private var bluetoothManager = BluetoothManager()
    @StateObject private var locationManager = LocationManager()
    @StateObject private var visionService = VisionService()
    @StateObject private var cameraManager = CameraManager()
    @StateObject private var speechManager = SpeechManager()
    @StateObject private var voiceAssistantManager = VoiceAssistantManager()
    @StateObject private var languageManager = AppLanguageManager.shared

    @State private var showSplash = true
    @State private var showLoginSheet = false

    var body: some Scene {
        WindowGroup {
            ZStack {
                MainTabView()
                    .environmentObject(bluetoothManager)
                    .environmentObject(locationManager)
                    .environmentObject(visionService)
                    .environmentObject(cameraManager)
                    .environmentObject(speechManager)
                    .environmentObject(voiceAssistantManager)
                    .environmentObject(languageManager)
                    .environmentObject(AuthManager.shared)
                    .preferredColorScheme(.none) // Follow the system appearance.
                    .onAppear {
                        configureSpeechPlaybackVolume()
                        setupAccessibility()
                        presentAccountLoginIfConfigured()
                    }
                    .onChange(of: AuthManager.shared.showLoginSheet) { _, newValue in
                        // Defer state changes until the current view update completes.
                        DispatchQueue.main.async {
                            showLoginSheet = newValue
                        }
                    }

                if showSplash {
                    SplashView {
                        withAnimation {
                            showSplash = false
                        }
                    }
                    .transition(.opacity)
                    .zIndex(1)
                }
            }
            .sheet(isPresented: $showLoginSheet) {
                LoginView()
                    .environmentObject(AuthManager.shared)
            }
        }
    }

    private func setupAccessibility() {
        UIAccessibility.post(notification: .announcement,
                              argument: languageManager.text("app_started"))
    }

    private func configureSpeechPlaybackVolume() {
        speechManager.prepareExternalPlayback = {
            HeyCyanService.shared.boostGlassesVolumeForPlayback()
        }
    }

    private func presentAccountLoginIfConfigured() {
        guard !AppRuntime.isRunningForPreviews,
              CloudBaseService.shared.isConfigured else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
            Task { @MainActor in
                if CloudBaseService.shared.isConfigured,
                   !AuthManager.shared.isLoggedIn {
                    AuthManager.shared.presentLogin()
                }
            }
        }
    }
}
