//
//  SettingsView.swift
//  LiberEye
//
//  Settings for cloud services, speech, and obstacle alerts.
//

import AVFoundation
import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var speechManager: SpeechManager
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var authManager: AuthManager
    @EnvironmentObject var languageManager: AppLanguageManager

    // CloudBase configuration
    @State private var envId: String = UserDefaults.standard.string(forKey: "cb_env_id") ?? CloudBaseDefaults.envId
    @State private var publishableKey: String = UserDefaults.standard.string(forKey: "cb_publishable_key") ?? CloudBaseDefaults.publishableKey
    @State private var showCloudBaseSection = false
    @State private var showDirectVisionSection = false
    @State private var isTestingConnection: Bool = false
    @State private var connectionStatus: ConnectionStatus = .notConfigured

    enum ConnectionStatus: Equatable {
        case notConfigured, notTested, connecting, connected, failed

        var text: String {
            let language = AppLanguageManager.shared
            switch self {
            case .notConfigured: return language.text("not_configured")
            case .notTested: return language.text("cloud_not_tested")
            case .connecting: return language.text("connecting")
            case .connected: return language.text("connected_status")
            case .failed: return language.text("connection_failed")
            }
        }

        var color: Color {
            switch self {
            case .notConfigured, .notTested: return .gray
            case .connecting: return .orange
            case .connected: return .green
            case .failed: return .red
            }
        }

        var icon: String {
            switch self {
            case .notConfigured, .notTested: return "cloud.fill"
            case .connecting: return "cloud.fill"
            case .connected: return "checkmark.icloud.fill"
            case .failed: return "exclamationmark.icloud.fill"
            }
        }
    }

    // Doubao API configuration
    @State private var apiKey: String = DoubaoConfig.apiKey
    @State private var modelId: String = DoubaoConfig.modelId
    @State private var showAPIKey = false
    @State private var apiSaveSuccess = false

    // LiberEye Cloud configuration
    @AppStorage("libereye_cloud_enabled") private var liberEyeCloudEnabled: Bool = true
    @State private var liberEyeCloudBaseURL = LiberEyeCloudConfig.baseURL
    @State private var liberEyeCloudToken = LiberEyeCloudConfig.apiToken
    @State private var isTestingLiberEyeCloud: Bool = false
    @State private var liberEyeCloudStatus: ConnectionStatus = .notConfigured
    @State private var liberEyeCloudMessage = ""
    @StateObject private var cloudService = LiberEyeCloudService.shared

    // Speech settings
    @AppStorage("speech_rate") private var speechRate: Double = 0.72
    @AppStorage("auto_obstacle_voice") private var autoObstacleVoice: Bool = true
    @AppStorage("obstacle_voice_threshold") private var obstacleVoiceThreshold: Int = 1
    private let minimumSpeechRate = Double(AVSpeechUtteranceMinimumSpeechRate)
    private let maximumSpeechRate = Double(AVSpeechUtteranceMaximumSpeechRate)

    // Obstacle detection settings
    @AppStorage("obstacle_alert_distance") private var alertDistance: Double = 3.0
    @AppStorage("vibration_enabled") private var vibrationEnabled: Bool = true
    @AppStorage("glasses_timed_analysis_enabled") private var glassesTimedAnalysisEnabled: Bool = false
    @AppStorage("glasses_timed_analysis_interval") private var glassesTimedAnalysisInterval: Double = 8.0

    var body: some View {
        NavigationStack {
            ZStack {
                LGStyle.backgroundGradient.ignoresSafeArea()

                Form {
                Section {
                    Toggle(languageManager.text("cloud_enabled"), isOn: $liberEyeCloudEnabled)
                        .accessibilityLabel(languageManager.text("cloud_enabled"))
                        .disabled(isTestingLiberEyeCloud)
                        .onChange(of: liberEyeCloudEnabled) { _, _ in
                            bluetoothManager.stopVibration()
                            speechManager.stopSpeaking()
                            cloudService.beginNavigationSession()
                        }

                    HStack {
                        Image(systemName: "network")
                            .foregroundColor(.teal)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(languageManager.text("cloud_address"))
                                .font(.caption)
                                .foregroundColor(.secondary)
                            TextField("https://libereye.example.org", text: $liberEyeCloudBaseURL)
                                .font(.system(size: 14, design: .monospaced))
                                .keyboardType(.URL)
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                                .disabled(isTestingLiberEyeCloud)
                                .accessibilityLabel(languageManager.text("cloud_address"))
                        }
                    }

                    HStack {
                        Image(systemName: "key.horizontal.fill")
                            .foregroundColor(.orange)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(languageManager.text("cloud_token"))
                                .font(.caption)
                                .foregroundColor(.secondary)
                            SecureField(languageManager.text("cloud_enter_token"), text: $liberEyeCloudToken)
                                .font(.system(size: 14, design: .monospaced))
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                                .disabled(isTestingLiberEyeCloud)
                                .accessibilityLabel(languageManager.text("cloud_token"))
                        }
                    }

                    HStack {
                        Image(systemName: liberEyeCloudStatus.icon)
                            .foregroundColor(liberEyeCloudStatus.color)
                        Text(languageManager.text("cloud_connection_status"))
                        Spacer()
                        if isTestingLiberEyeCloud {
                            ProgressView()
                                .scaleEffect(0.7)
                        }
                        Text(cloudStatusText)
                            .font(.caption)
                            .foregroundColor(liberEyeCloudStatus.color)
                    }

                    if !liberEyeCloudMessage.isEmpty {
                        Text(liberEyeCloudMessage)
                            .font(.caption)
                            .foregroundColor(liberEyeCloudStatus == .failed ? .red : .secondary)
                    }

                    Button {
                        _ = saveLiberEyeCloudConfiguration()
                    } label: {
                        Label(languageManager.text("cloud_save"), systemImage: "square.and.arrow.down")
                    }
                    .disabled(isTestingLiberEyeCloud)

                    Button {
                        testLiberEyeCloudConnection()
                    } label: {
                        Label(languageManager.text(isTestingLiberEyeCloud ? "cloud_testing" : "cloud_test"),
                              systemImage: isTestingLiberEyeCloud ? "arrow.triangle.2.circlepath" : "checkmark.seal.fill")
                            .frame(maxWidth: .infinity, minHeight: 44)
                            .fontWeight(.semibold)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .tint(.teal)
                    .disabled(isTestingLiberEyeCloud || liberEyeCloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || liberEyeCloudToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .opacity(isTestingLiberEyeCloud || liberEyeCloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || liberEyeCloudToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.55 : 1)
                    .accessibilityLabel(languageManager.text("cloud_test"))
                } header: {
                    Label(languageManager.text("cloud_service"), systemImage: "cloud.fill")
                } footer: {
                    Text(languageManager.text("cloud_settings_footer"))
                }

                Section {
                    DisclosureGroup(languageManager.text("cloudbase_optional"), isExpanded: $showCloudBaseSection) {
                    Text(languageManager.text("cloudbase_footer"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                    // Connection state
                    HStack {
                        Image(systemName: connectionStatus.icon)
                            .foregroundColor(connectionStatus.color)
                        Text(languageManager.text("cloudbase_status"))
                        Spacer()
                        if isTestingConnection {
                            ProgressView()
                                .scaleEffect(0.7)
                        }
                        Text(connectionStatus.text)
                            .font(.caption)
                            .foregroundColor(connectionStatus.color)
                    }
                    .accessibilityLabel("\(languageManager.text("cloudbase_status")): \(connectionStatus.text)")

                    // Environment ID
                    HStack {
                        Image(systemName: "server.rack")
                            .foregroundColor(.blue)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(languageManager.text("env_id"))
                                .font(.caption)
                                .foregroundColor(.secondary)
                            TextField(languageManager.text("enter_env_id"), text: $envId)
                                .font(.system(size: 14, design: .monospaced))
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                        }
                    }
                    .accessibilityLabel("CloudBase environment ID field")

                    // Publishable Key
                    HStack {
                        Image(systemName: "key.fill")
                            .foregroundColor(.orange)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Publishable Key")
                                .font(.caption)
                                .foregroundColor(.secondary)
                            SecureField(languageManager.text("enter_publishable_key"), text: $publishableKey)
                                .font(.system(size: 14, design: .monospaced))
                                .autocorrectionDisabled()
                                .textInputAutocapitalization(.never)
                        }
                    }
                    .accessibilityLabel("Publishable Key field")

                    // Save and connect
                    Button(action: saveAndConnect) {
                        HStack {
                            Image(systemName: "link")
                            Text(languageManager.text("save_connect"))
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .glassActionButton(color: .blue, cornerRadius: 12)
                        .foregroundColor(.white)
                        .fontWeight(.medium)
                    }
                    .accessibilityLabel("Save and connect to CloudBase")

                    // Sign-in state
                    if authManager.isLoggedIn {
                        HStack {
                            Image(systemName: authManager.isPhoneLogin ? "person.fill" : "person.crop.circle")
                                .foregroundColor(.green)
                            Text(authManager.isPhoneLogin ? languageManager.text("logged_in_phone") : languageManager.text("logged_in_guest"))
                                .font(.caption)
                                .foregroundColor(.green)
                            Spacer()
                            Button(languageManager.text("logout")) {
                                Task { await authManager.logout() }
                            }
                            .font(.caption)
                            .foregroundColor(.red)
                        }
                        .accessibilityLabel("CloudBase sign-in status, signed in")
                    } else {
                        Button(action: { authManager.presentLogin() }) {
                            HStack {
                                Image(systemName: "person.badge.plus")
                                Text(languageManager.text("login_cloudbase"))
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 10)
                            .glassActionButton(color: .purple, cornerRadius: 12)
                            .foregroundColor(.white)
                            .fontWeight(.medium)
                        }
                        .accessibilityLabel("Sign in to a CloudBase account")
                    }

                    }
                } header: {
                    Label(languageManager.text("cloudbase_service"), systemImage: "cloud.fill")
                } footer: {
                    Text(languageManager.text("cloudbase_optional_note"))
                }
                Section {
                    DisclosureGroup(languageManager.text("direct_vision_optional"), isExpanded: $showDirectVisionSection) {
                    apiKeyField
                    modelIdField
                    saveAPIButton
                    }
                } header: {
                    Label(languageManager.text("doubao_config"), systemImage: "sparkles")
                } footer: {
                    Text(languageManager.text("direct_vision_note"))
                }

                // Speech settings
                Section {
                    Toggle(languageManager.text("auto_obstacle_voice"), isOn: $autoObstacleVoice)
                        .accessibilityLabel("Toggle automatic obstacle announcements")

                    VStack(alignment: .leading, spacing: 6) {
                        Text(languageManager.text("speech_rate"))
                        HStack {
                            Image(systemName: "tortoise.fill")
                                .foregroundColor(.secondary)
                            Slider(value: $speechRate, in: minimumSpeechRate...maximumSpeechRate, step: 0.03)
                            Image(systemName: "hare.fill")
                                .foregroundColor(.secondary)
                        }
                        HStack {
                            Text(languageManager.format("current_percent", speechRate * 100))
                                .font(.caption)
                                .foregroundColor(.secondary)
                            Spacer()
                            Button("Very fast") {
                                speechRate = min(maximumSpeechRate, 0.86)
                                speechManager.speak("Speech rate set to very fast.")
                            }
                            .buttonStyle(.borderless)
                            Button("Maximum") {
                                speechRate = maximumSpeechRate
                                speechManager.speak("Speech rate set to maximum.")
                            }
                            .buttonStyle(.borderless)
                        }
                    }

                    Picker(languageManager.text("voice_threshold"), selection: $obstacleVoiceThreshold) {
                        Text(languageManager.text("caution_above")).tag(1)
                        Text(languageManager.text("warning_above")).tag(2)
                        Text(languageManager.text("danger_above")).tag(3)
                    }
                    .accessibilityLabel("Select the hazard level that triggers obstacle announcements")

                    Button(action: {
                        speechManager.speak(languageManager.text("app_started"), priority: .normal, rate: Float(speechRate))
                    }) {
                        HStack {
                            Image(systemName: "waveform")
                                .foregroundColor(.blue)
                            Text(languageManager.text("test_voice"))
                                .foregroundColor(.blue)
                        }
                    }
                    .accessibilityLabel("Test speech playback")

                } header: {
                    Label(languageManager.text("voice_settings"), systemImage: "speaker.wave.2.fill")
                }

                // Obstacle detection settings
                Section {
                    Toggle(languageManager.text("enable_bracelet_vibration"), isOn: $vibrationEnabled)
                        .accessibilityLabel("Toggle band vibration")
                        .onChange(of: vibrationEnabled) { _, enabled in
                            if !enabled {
                                bluetoothManager.sendVibration(VibrationCommand(pattern: .stop, duration: 0))
                            }
                        }

                    #if LIBEREYE_WITH_HEYCYAN
                    Toggle(languageManager.text("glasses_timed_analysis"), isOn: $glassesTimedAnalysisEnabled)
                        .accessibilityLabel("Toggle timed photo analysis from glasses")

                    VStack(alignment: .leading, spacing: 6) {
                        Text(languageManager.format("glasses_analysis_interval", glassesTimedAnalysisInterval))
                        Slider(value: $glassesTimedAnalysisInterval, in: 5.0...60.0, step: 1.0)
                            .disabled(!glassesTimedAnalysisEnabled)
                            .accessibilityLabel("Adjust the glasses photo analysis interval")
                        HStack {
                            Text(languageManager.text("five_seconds_fast"))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            Spacer()
                            Text(languageManager.text("sixty_seconds_quiet"))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    }

                    #endif

                    VStack(alignment: .leading, spacing: 6) {
                        Text(languageManager.format("alert_distance", alertDistance))
                        Slider(value: $alertDistance, in: 1.0...5.0, step: 0.5)
                            .accessibilityLabel("Adjust the obstacle alert distance")
                        HStack {
                            Text(languageManager.text("one_meter_near"))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            Spacer()
                            Text(languageManager.text("five_meter_far"))
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                    }

                } header: {
                    Label(languageManager.text("obstacle_detection"), systemImage: "shield.fill")
                }

                // About
                Section {
                    LabeledContent(languageManager.text("version"), value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "")
                    LabeledContent(languageManager.text("developer"), value: "LiberEye Team")

                    Link(destination: URL(string: "https://www.volcengine.com/product/doubao")!) {
                        HStack {
                            Image(systemName: "link")
                                .foregroundColor(.blue)
                            Text(languageManager.text("doubao_website"))
                                .foregroundColor(.blue)
                        }
                    }
                    .accessibilityLabel(languageManager.text("doubao_website"))

                } header: {
                    Label(languageManager.text("about"), systemImage: "info.circle")
                }
            }
            .liquidGlassSystemList()
            .safeAreaInset(edge: .bottom) {
                Color.clear.frame(height: LGStyle.tabBarAvoidanceHeight)
            }
            .navigationTitle(languageManager.text("settings"))
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
        }
        }
        .onChange(of: apiKey) { _, _ in apiSaveSuccess = false }
        .onChange(of: modelId) { _, _ in apiSaveSuccess = false }
        .onAppear {
            repairLiberEyeCloudDefaults()
            liberEyeCloudStatus = LiberEyeCloudConfig.isConfigured ? .notTested : .notConfigured
        }
        .onChange(of: liberEyeCloudBaseURL) { _, _ in invalidateCloudStatus() }
        .onChange(of: liberEyeCloudToken) { _, _ in invalidateCloudStatus() }
    }

    // MARK: - API Key field
    private var apiKeyField: some View {
        HStack {
            Image(systemName: "key.fill")
                .foregroundColor(.orange)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 2) {
                Text("API Key")
                    .font(.caption)
                    .foregroundColor(.secondary)
                Group {
                    if showAPIKey {
                        TextField(languageManager.text("enter_doubao_key"), text: $apiKey)
                    } else {
                        SecureField(languageManager.text("enter_doubao_key"), text: $apiKey)
                    }
                }
                .font(.system(size: 14, design: .monospaced))
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            }

            Button(action: { showAPIKey.toggle() }) {
                Image(systemName: showAPIKey ? "eye.slash" : "eye")
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
        }
        .accessibilityLabel("Doubao API Key field")
    }

    // MARK: - Model ID field
    private var modelIdField: some View {
        HStack {
            Image(systemName: "cpu")
                .foregroundColor(.purple)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.text("model_id"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                TextField("For example: doubao-seed-1-6-flash-250828", text: $modelId)
                    .font(.system(size: 14, design: .monospaced))
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
            }
        }
        .accessibilityLabel("Doubao model ID field")
    }

    // MARK: - Save API settings button
    private var saveAPIButton: some View {
        Button(action: {
            DoubaoConfig.save(apiKey: apiKey, modelId: modelId)
            apiSaveSuccess = true
            speechManager.speak(languageManager.text("api_saved_voice"))
        }) {
            HStack {
                Image(systemName: apiSaveSuccess ? "checkmark.circle.fill" : "square.and.arrow.down.fill")
                    .foregroundColor(apiSaveSuccess ? .green : .blue)
                Text(apiSaveSuccess ? languageManager.text("saved") : languageManager.text("save_api_config"))
                    .fontWeight(.medium)
                    .foregroundColor(apiSaveSuccess ? .green : .blue)
            }
        }
        .disabled(apiKey.isEmpty)
        .accessibilityLabel("Save Doubao API settings")
    }

    // MARK: - CloudBase connection
    private func saveAndConnect() {
        guard !envId.isEmpty else {
            connectionStatus = .failed
            return
        }

        isTestingConnection = true
        connectionStatus = .connecting

        // Save configuration
        UserDefaults.standard.set(envId, forKey: "cb_env_id")
        UserDefaults.standard.set(publishableKey, forKey: "cb_publishable_key")

        // Configure the service
        CloudBaseService.shared.configure(envId: envId)

        Task {
            let success = await CloudBaseService.shared.testConnection()
            await MainActor.run {
                isTestingConnection = false
                if success {
                    connectionStatus = .connected
                    speechManager.speak(languageManager.text("cloudbase_connected_voice"))
                    // Sign in as a guest automatically
                    Task { await authManager.loginAnonymously() }
                } else {
                    connectionStatus = .failed
                    speechManager.speak(languageManager.text("cloudbase_failed_voice"))
                }
            }
        }
    }

    private var cloudStatusText: String {
        guard liberEyeCloudStatus == .connected else { return liberEyeCloudStatus.text }
        switch cloudService.readinessMode {
        case .model: return languageManager.text("cloud_model_ready")
        case .heuristic: return languageManager.text("cloud_basic_ready")
        case nil: return liberEyeCloudStatus.text
        }
    }

    private func invalidateCloudStatus() {
        liberEyeCloudStatus = .notTested
        liberEyeCloudMessage = ""
    }

    @discardableResult
    private func saveLiberEyeCloudConfiguration() -> Bool {
        repairLiberEyeCloudDefaults()
        bluetoothManager.stopVibration()
        speechManager.stopSpeaking()
        do {
            try LiberEyeCloudConfig.save(
                baseURL: liberEyeCloudBaseURL,
                apiToken: liberEyeCloudToken,
                enabled: liberEyeCloudEnabled
            )
        } catch {
            liberEyeCloudStatus = .failed
            liberEyeCloudMessage = error.localizedDescription
            return false
        }
        liberEyeCloudStatus = .notTested
        liberEyeCloudMessage = languageManager.text("saved")
        return true
    }

    private func testLiberEyeCloudConnection() {
        guard saveLiberEyeCloudConfiguration() else {
            speechManager.speak(liberEyeCloudMessage, priority: .normal)
            return
        }
        isTestingLiberEyeCloud = true
        liberEyeCloudStatus = .connecting
        liberEyeCloudMessage = ""
        speechManager.speak(languageManager.text("cloud_testing"))

        Task {
            let success = await cloudService.testConnection()
            await MainActor.run {
                isTestingLiberEyeCloud = false
                liberEyeCloudStatus = success ? .connected : .failed
                if success {
                    liberEyeCloudMessage = cloudService.readinessMode == .heuristic
                        ? languageManager.text("cloud_basic_note") : ""
                } else {
                    liberEyeCloudMessage = cloudService.lastError ?? languageManager.text("connection_failed")
                }
                speechManager.speak(success ? cloudStatusText : liberEyeCloudMessage)
            }
        }
    }

    private func repairLiberEyeCloudDefaults() {
        liberEyeCloudBaseURL = liberEyeCloudBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        liberEyeCloudToken = liberEyeCloudToken.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
