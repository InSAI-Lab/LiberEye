//
//  ObstacleView.swift
//  LiberEye
//
//  Obstacle detection and perception view.
//

import SwiftUI

struct ObstacleView: View {
    @Environment(\.scenePhase) private var scenePhase
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var cameraManager: CameraManager
    @EnvironmentObject var speechManager: SpeechManager
    @EnvironmentObject var visionService: VisionService
    @EnvironmentObject var voiceAssistantManager: VoiceAssistantManager
    @EnvironmentObject var languageManager: AppLanguageManager
    @Binding var perceptionMode: PerceptionMode

    @StateObject private var heyCyanService = HeyCyanService.shared
    @StateObject private var liberEyeCloudService = LiberEyeCloudService.shared
    @State private var showModeAlert = false
    @State private var timedGlassesAnalysisTask: Task<Void, Never>?
    @State private var isTimedGlassesAnalysisRunning = false
    @State private var isDescribingCurrentView = false
    @State private var lastTimedGlassesAnalysisAt: Date?
    @State private var timedGlassesAnalysisStatus = ""
    @AppStorage("glasses_timed_analysis_enabled") private var glassesTimedAnalysisEnabled: Bool = false
    @AppStorage("glasses_timed_analysis_interval") private var glassesTimedAnalysisInterval: Double = 8.0

    var body: some View {
        NavigationStack {
            ZStack {
                // Liquid Glass background gradient
                LGStyle.backgroundGradient.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Scrollable content
                    ScrollView(showsIndicators: false) {
                        VStack(spacing: 0) {
                            // Top status area
                            statusHeader
                                .padding(.horizontal)
                                .padding(.vertical, 8)

                            if !LiberEyeCloudConfig.isEnabled || !LiberEyeCloudConfig.isConfigured {
                                cloudConfigurationNotice
                                    .padding(.horizontal)
                                    .padding(.bottom, 12)
                            }

                            // Perception mode selection
                            modeSwitcher
                                .padding(.horizontal)
                                .padding(.bottom, 12)

                            // Use compact status in glasses mode; prioritize the preview in phone camera mode.
                            if perceptionMode == .glasses {
                                compactDangerStatus
                                    .padding(.horizontal)
                            }

                            // Obstacle information card
                            if let obstacle = bluetoothManager.latestObstacle {
                                obstacleCard(obstacle)
                                    .padding(.horizontal)
                                    .padding(.top, 12)
                                    .transition(.move(edge: .bottom).combined(with: .opacity))
                            }

                            // Camera preview in phone mode
                            if perceptionMode == .phone && cameraManager.isRunning {
                                cameraPreview
                                    .padding(.top, 8)
                            }

                            if perceptionMode == .glasses {
                                GlassesCameraPreview(service: heyCyanService)
                                    .padding(.horizontal)
                                    .padding(.top, 6)

                                if glassesTimedAnalysisEnabled {
                                    timedAnalysisStatusCard
                                        .padding(.horizontal)
                                        .padding(.top, 8)
                                }
                            }
                        }
                        .padding(.bottom, 16)
                    }

                    // Fixed bottom controls above the tab bar.
                    bottomActions
                        .padding(.horizontal)
                        .padding(.top, 6)
                        .padding(.bottom, 106)
                }
            }
            .navigationTitle(languageManager.text("obstacle_detection"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    deviceStatusButton
                }
            }
        }
        .onAppear {
            guard !AppRuntime.isRunningForPreviews else { return }
            liberEyeCloudService.beginNavigationSession()
            heyCyanService.refreshConnectionStatus(autoConnect: true)
            bluetoothManager.autoConnectBraceletIfNeeded()
            if heyCyanService.deviceState == .connected {
                perceptionMode = .glasses
                cameraManager.stopSession()
            }
            updateTimedGlassesAnalysis()
            startVoiceAssistant()
        }
        .task(id: perceptionMode) {
            guard !AppRuntime.isRunningForPreviews, perceptionMode == .phone else { return }
            await cameraManager.checkPermissions()
            guard !Task.isCancelled, perceptionMode == .phone else { return }
            cameraManager.startSession()
        }
        .onDisappear {
            stopTimedGlassesAnalysis()
            liberEyeCloudService.beginNavigationSession()
            bluetoothManager.stopVibration()
            speechManager.stopSpeaking()
            voiceAssistantManager.stop()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                updateTimedGlassesAnalysis()
            } else {
                stopTimedGlassesAnalysis()
                liberEyeCloudService.beginNavigationSession()
                speechManager.stopSpeaking()
            }
        }
        .onChange(of: perceptionMode) { _, _ in updateTimedGlassesAnalysis() }
        .onChange(of: heyCyanService.deviceState) { _, _ in updateTimedGlassesAnalysis() }
        .onChange(of: glassesTimedAnalysisEnabled) { _, _ in updateTimedGlassesAnalysis() }
        .onChange(of: glassesTimedAnalysisInterval) { _, _ in restartTimedGlassesAnalysisIfNeeded() }
        .animation(.easeInOut(duration: 0.3), value: bluetoothManager.currentDangerLevel)
        .animation(.easeInOut(duration: 0.3), value: bluetoothManager.latestObstacle?.id)
    }

    private var cloudConfigurationNotice: some View {
        VStack(alignment: .leading, spacing: 5) {
            Label(languageManager.text(LiberEyeCloudConfig.isEnabled ? "cloud_setup_required" : "cloud_disabled"), systemImage: "cloud")
                .font(.subheadline.bold())
            Text(languageManager.text(LiberEyeCloudConfig.isEnabled ? "cloud_setup_description" : "cloud_disabled_description"))
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .glassCard(cornerRadius: 12)
        .accessibilityElement(children: .combine)
    }

    // MARK: - Top status header
    private var statusHeader: some View {
        HStack(spacing: 10) {
            // Glasses connection state
            #if LIBEREYE_WITH_HEYCYAN
            HeyCyanDeviceStatusPill(service: heyCyanService)
            #endif

            // Band connection state
            DeviceStatusPill(
                icon: "applewatch",
                label: languageManager.text("bracelet"),
                state: bluetoothManager.braceletState
            )

            Spacer()

            // Speech state
            if speechManager.isSpeaking {
                HStack(spacing: 4) {
                    Image(systemName: "waveform")
                        .foregroundColor(.blue)
                        .symbolEffect(.variableColor)
                    Text(languageManager.text("speaking"))
                        .font(.caption)
                        .foregroundColor(.blue)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .glassCapsule()
            }

            if isTimedGlassesAnalysisRunning {
                HStack(spacing: 4) {
                    Image(systemName: "camera.metering.center.weighted")
                        .foregroundColor(.purple)
                    Text(languageManager.text("capturing"))
                        .font(.caption)
                        .foregroundColor(.purple)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .glassCapsule()
            } else if glassesTimedAnalysisEnabled && perceptionMode == .glasses && heyCyanService.deviceState == .connected {
                HStack(spacing: 4) {
                    Image(systemName: "timer")
                        .foregroundColor(.purple)
                    Text(languageManager.text("timed_capture"))
                        .font(.caption)
                        .foregroundColor(.purple)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .glassCapsule()
            }
        }
    }

    // MARK: - Perception mode switch
    private var modeSwitcher: some View {
        HStack(spacing: 0) {
            ForEach(PerceptionMode.availableModes, id: \.self) { mode in
                Button(action: {
                    switchMode(to: mode)
                }) {
                    HStack(spacing: 6) {
                        Image(systemName: mode.icon)
                            .font(.system(size: 14))
                    Text(mode.displayName)
                            .font(.system(size: 14, weight: .medium))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(perceptionMode == mode
                                  ? Color.blue
                                  : Color.clear)
                            .shadow(color: perceptionMode == mode ? Color.blue.opacity(0.3) : .clear,
                                    radius: 6, y: 2)
                    )
                    .foregroundColor(perceptionMode == mode ? .white : .primary)
                }
                .buttonStyle(.plain)
                .opacity(mode == .glasses && heyCyanService.deviceState != .connected ? 0.55 : 1)
                .accessibilityLabel(mode.description)
            }
        }
        .padding(4)
        .glassCard(cornerRadius: 16, material: .regularMaterial)
    }

    // MARK: - Primary hazard status
    private var mainDangerDisplay: some View {
        let level = bluetoothManager.currentDangerLevel

        return ZStack {
            // Glass halo background
            Circle()
                .fill(.ultraThinMaterial)
                .overlay(
                    Circle()
                        .fill(level.color.opacity(0.12))
                )
                .overlay(
                    Circle()
                        .stroke(level.color.opacity(0.25), lineWidth: 2)
                )
                .frame(width: 136, height: 136)
                .scaleEffect(level >= .high ? 1.08 : 1.0)
                .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true),
                           value: level)
                .shadow(color: level.color.opacity(0.18), radius: 18, y: 4)

            // Inner ring border
            Circle()
                .stroke(level.color.opacity(0.35), lineWidth: 2)
                .frame(width: 106, height: 106)

            VStack(spacing: 5) {
                Image(systemName: dangerIcon(for: level))
                    .font(.system(size: 38))
                    .foregroundColor(level.color)
                    .symbolEffect(.bounce, value: level)

                Text(level.displayText)
                    .font(.system(size: 22, weight: .bold, design: .rounded))
                    .foregroundColor(level.color)

                if level != .safe {
                    Text(level.vibrationDescription)
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
        }
        .frame(height: 150)
        .accessibilityLabel("Current safety status: \(level.displayText)")
    }

    private var compactDangerStatus: some View {
        let level = bluetoothManager.currentDangerLevel

        return HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(level.color.opacity(0.14))
                    .frame(width: 48, height: 48)
                Image(systemName: dangerIcon(for: level))
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundColor(level.color)
                    .symbolEffect(.bounce, value: level)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(level.displayText)
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundColor(level.color)
                Text(level == .safe ? "No obstacle alerts received" : level.vibrationDescription)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
            }

            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .glassCard(cornerRadius: 16, material: .thinMaterial)
        .accessibilityLabel("Current safety status: \(level.displayText)")
    }

    // MARK: - Obstacle information card
    private func obstacleCard(_ obstacle: ObstacleInfo) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundColor(obstacle.dangerLevel.color)
                    Text(languageManager.text("obstacle_detected"))
                    .font(.headline)
                Spacer()
                Text(timeAgo(obstacle.timestamp))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            HStack(spacing: 16) {
                infoItem(title: languageManager.text("direction"), value: obstacle.direction, icon: "arrow.up.circle")
                infoItem(title: languageManager.text("distance"), value: String(format: "%.1fm", obstacle.distance), icon: "ruler")
                infoItem(title: languageManager.text("type"), value: obstacle.description, icon: "cube")
            }
        }
        .padding()
        .glassCard()
        .overlay(
            RoundedRectangle(cornerRadius: LGStyle.cardCornerRadius)
                .stroke(obstacle.dangerLevel.color.opacity(0.30), lineWidth: 1)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(obstacle.voiceAlert)
    }

    private func infoItem(title: String, value: String, icon: String) -> some View {
        VStack(spacing: 2) {
            Image(systemName: icon)
                .font(.system(size: 18))
                .foregroundColor(.secondary)
            Text(value)
                .font(.system(size: 15, weight: .semibold))
            Text(title)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Camera preview
    private var cameraPreview: some View {
        CameraPreview(session: cameraManager.session)
            .frame(height: 430)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal)
            .overlay(alignment: .topTrailing) {
                Label(languageManager.text("live"), systemImage: "record.circle.fill")
                    .font(.caption)
                    .foregroundColor(.white)
                    .padding(6)
                    .background(Capsule().fill(Color.red.opacity(0.8)))
                    .padding(.trailing, 24)
                    .padding(.top, 8)
            }
    }

    private var timedAnalysisStatusCard: some View {
        HStack(spacing: 8) {
            Image(systemName: isTimedGlassesAnalysisRunning ? "camera.metering.center.weighted" : "timer")
                .foregroundColor(.purple)

            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.text("glasses_timed_capture"))
                    .font(.caption)
                    .fontWeight(.semibold)
                Text(timedAnalysisDetailText)
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }

            Spacer()
        }
        .padding(10)
        .glassCard(cornerRadius: 12, material: .thinMaterial)
    }

    // MARK: - Bottom action buttons
    private var bottomActions: some View {
        HStack(spacing: 12) {
            LargeActionButton(
                icon: "speaker.wave.2.fill",
                label: languageManager.text("speak_status"),
                color: .blue
            ) {
                speakCurrentStatus()
            }

            LargeActionButton(
                icon: isDescribingCurrentView ? "camera.metering.center.weighted" : "camera.viewfinder",
                label: languageManager.text("describe_view"),
                color: .purple
            ) {
                describeCurrentView()
            }
        }
    }

    // MARK: - Device status buttons
    private var deviceStatusButton: some View {
        #if LIBEREYE_WITH_HEYCYAN
        let deviceCount = 2
        let connectedCount = (heyCyanService.deviceState == .connected ? 1 : 0) +
                            (bluetoothManager.braceletState == .connected ? 1 : 0)
        #else
        let deviceCount = 1
        let connectedCount = bluetoothManager.braceletState == .connected ? 1 : 0
        #endif
        return HStack(spacing: 4) {
            Circle()
                .fill(connectedCount == deviceCount ? Color.green : connectedCount > 0 ? Color.yellow : Color.gray)
                .frame(width: 8, height: 8)
            Text("\(connectedCount)/\(deviceCount)")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(
            Capsule()
                .fill(.ultraThinMaterial)
                .overlay(Capsule().stroke(Color.white.opacity(0.5), lineWidth: 1))
        )
    }

    // MARK: - Helper methods
    private func switchMode(to mode: PerceptionMode) {
        if mode == .glasses && heyCyanService.deviceState != .connected {
            heyCyanService.refreshConnectionStatus(autoConnect: true)
            speechManager.speak("Connecting glasses. Please wait.")
            return
        }
        withAnimation {
            perceptionMode = mode
        }
        if mode == .glasses {
            cameraManager.stopSession()
            speechManager.speak("Switched to glasses mode.")
        } else {
            cameraManager.startSession()
            speechManager.speak("Switched to phone camera mode.")
        }
    }

    private func speakCurrentStatus() {
        if let obstacle = bluetoothManager.latestObstacle, obstacle.dangerLevel != .safe {
            speechManager.speak(obstacle.voiceAlert, priority: .normal)
        } else {
            speechManager.speak(currentStatusVoiceText(), priority: .normal)
        }
    }

    private func currentStatusVoiceText() -> String {
        switch perceptionMode {
        case .phone:
            if cameraManager.isRunning {
                return "The phone camera preview is active without continuous safety assessment. Tap Describe, or say LiberEye, describe the current view, to analyze what is ahead."
            }
            return "The phone camera is off. No environmental safety assessment is available."
        case .glasses:
            if heyCyanService.deviceState != .connected {
                return "Glasses are disconnected. No obstacle data is available from the glasses."
            }
            if bluetoothManager.lastObstacleUpdateAt == nil {
                return "Glasses are connected, but no obstacle data has been received."
            }
            return "There are no obstacle alerts to announce. This does not establish that the surroundings are safe."
        }
    }

    private func describeCurrentView() {
        guard !isDescribingCurrentView && !visionService.isAnalyzing else {
            speechManager.speak(languageManager.text("analysis_busy_skip"), priority: .normal)
            return
        }

        Task {
            isDescribingCurrentView = true
            defer { isDescribingCurrentView = false }

            let image: UIImage?
            if perceptionMode == .glasses {
                image = await heyCyanService.captureCurrentGlassesFrame()
            } else {
                if !cameraManager.isRunning {
                    await cameraManager.checkPermissions()
                    cameraManager.startSession()
                }
                image = await cameraManager.capturePhotoAsync()
            }

            guard let image else {
                speechManager.speak(missingFrameMessage, priority: .normal)
                return
            }

            if LiberEyeCloudConfig.isEnabled {
                do {
                    let plan = try await liberEyeCloudService.analyze(
                        image: image,
                        targetQuery: "Briefly describe the current view, including the setting, main objects, visible mobility hazards, and suggested next action. Respond in English.",
                        detailRequest: true,
                        wristConnected: bluetoothManager.canDeliverFeedback
                    )
                    dispatchCloudPlan(plan)
                    return
                } catch {
                    if error is CancellationError { return }
                    liberEyeCloudService.lastError = error.localizedDescription
                    bluetoothManager.stopVibration()
                    speakAssistantMessage("Cloud analysis failed. Please try again later.")
                    return
                }
            }

            await visionService.analyze(image: image, mode: .scene)

            if let result = visionService.lastResult {
                speakAssistantResult(result)
            } else if let error = visionService.error {
                speakAssistantMessage(error)
            }
        }
    }

    private func startVoiceAssistant() {
        voiceAssistantManager.start { command in
            Task { @MainActor in
                await handleVoiceAssistantCommand(command)
            }
        }
    }

    private func handleVoiceAssistantCommand(_ command: String) async {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            speechManager.speak(languageManager.text("assistant_awake"), priority: .normal)
            return
        }

        if shouldUseVision(for: trimmed) {
            await answerVisionQuestion(trimmed)
        } else {
            await answerTextQuestion(trimmed)
        }
    }

    private func shouldUseVision(for text: String) -> Bool {
        let keywords = ["describe", "see", "look", "view", "camera", "photo", "picture", "image",
                        "ahead", "front", "around", "surroundings", "environment", "obstacle",
                        "text", "read", "recognize", "recognise", "sign", "color", "colour"]
        let words = Set(text.lowercased().split { !$0.isLetter }.map(String.init))
        return keywords.contains { words.contains($0) }
    }

    private func answerVisionQuestion(_ question: String) async {
        guard !visionService.isAnalyzing else {
            speechManager.speak(languageManager.text("analysis_busy_skip"), priority: .normal)
            return
        }

        let image: UIImage?
        if perceptionMode == .glasses {
            image = await heyCyanService.captureCurrentGlassesFrame()
        } else {
            if !cameraManager.isRunning {
                await cameraManager.checkPermissions()
                cameraManager.startSession()
            }
            image = await cameraManager.capturePhotoAsync()
        }

        guard let image else {
            speechManager.speak(missingFrameMessage, priority: .normal)
            return
        }

        if LiberEyeCloudConfig.isEnabled {
            do {
                let plan = try await liberEyeCloudService.analyze(
                    image: image, targetQuery: question, detailRequest: true,
                    wristConnected: bluetoothManager.canDeliverFeedback
                )
                dispatchCloudPlan(plan)
            } catch {
                guard !(error is CancellationError) else { return }
                bluetoothManager.stopVibration()
                liberEyeCloudService.lastError = error.localizedDescription
                speakAssistantMessage("Cloud analysis failed. Please try again later.")
            }
            return
        }

        let words = Set(question.lowercased().split { !$0.isLetter }.map(String.init))
        let mode = words.contains("text") || words.contains("read") ? SceneAnalysisMode.text : SceneAnalysisMode.scene
        speakAssistantMessage(languageManager.text("assistant_thinking"))
        await visionService.analyze(image: image, mode: mode)

        if let result = visionService.lastResult {
            speakAssistantResult(result)
        } else if let error = visionService.error {
            speakAssistantMessage(error)
        }
    }

    private func answerTextQuestion(_ question: String) async {
        guard !visionService.isAnalyzing else {
            speechManager.speak(languageManager.text("analysis_busy_skip"), priority: .normal)
            return
        }

        speakAssistantMessage(languageManager.text("assistant_thinking"))
        let context = currentAssistantContext()
        if let answer = await visionService.ask(question, context: context) {
            speakAssistantMessage(answer)
        } else if let error = visionService.error {
            speakAssistantMessage(error)
        }
    }

    private func currentAssistantContext() -> String {
        switch perceptionMode {
        case .phone:
            return "Phone camera mode is active. Images are sent to the vision model only for photo analysis or an explicit request to inspect the view. Do not claim that the surroundings are safe. Respond in English."
        case .glasses:
            if let obstacle = bluetoothManager.latestObstacle, obstacle.dangerLevel != .safe {
                return "The glasses currently report this obstacle: \(obstacle.voiceAlert). Respond in English."
            }
            return "Glasses mode is active. There are no obstacle alerts to announce, which does not establish that the surroundings are safe. Respond in English."
        }
    }

    private func speakAssistantResult(_ result: SceneAnalysisResult) {
        voiceAssistantManager.muteTemporarily(seconds: estimatedSpeechDuration(for: result.voiceText))
        speechManager.speakAnalysisResult(result)
    }

    private func dispatchCloudPlan(_ plan: LiberEyeCloudPlan) {
        RelayOutputCoordinator.dispatch(plan, bluetooth: bluetoothManager, speech: speechManager)
    }

    private func speakAssistantMessage(_ text: String, rate: Float? = nil) {
        voiceAssistantManager.muteTemporarily(seconds: estimatedSpeechDuration(for: text))
        speechManager.speak(text, priority: .normal, rate: rate)
    }

    private func estimatedSpeechDuration(for text: String) -> TimeInterval {
        let duration = Double(text.count) * 0.18 + 1.5
        return min(max(duration, 3.0), 18.0)
    }

    private var missingFrameMessage: String {
        guard perceptionMode == .glasses else {
            return languageManager.text("photo_failed")
        }

        if heyCyanService.pendingFrameMessageAvailable {
            return "The glasses image is still transferring. Please try again shortly."
        }

        return languageManager.text("no_glasses_frame")
    }

    private func simulateObstacle() {
        let distances: [Double] = [0.4, 0.8, 1.5, 2.5, 4.0]
        let directions = [0, 1, 2]
        let types = [0, 1, 2, 3]
        bluetoothManager.simulateObstacleData(
            direction: directions.randomElement()!,
            distance: distances.randomElement()!,
            objectType: types.randomElement()!
        )
    }

    private var timedAnalysisDetailText: String {
        if heyCyanService.deviceState != .connected {
            return languageManager.text("waiting_for_glasses")
        }
        if perceptionMode != .glasses {
            return languageManager.text("switch_to_glasses_to_start")
        }
        if isTimedGlassesAnalysisRunning {
            return timedGlassesAnalysisStatus.isEmpty ? languageManager.text("capturing_glasses_photo") : timedGlassesAnalysisStatus
        }
        if let lastTimedGlassesAnalysisAt {
            let seconds = Int(Date().timeIntervalSince(lastTimedGlassesAnalysisAt))
            return languageManager.format("last_capture_seconds", seconds, Int(glassesTimedAnalysisInterval))
        }
        if !LiberEyeCloudConfig.isConfigured {
            return "Configure LiberEye Cloud."
        }
        return languageManager.format("waiting_next_capture", Int(glassesTimedAnalysisInterval))
    }

    private var canRunTimedGlassesAnalysis: Bool {
        scenePhase == .active
        && glassesTimedAnalysisEnabled
        && perceptionMode == .glasses
        && heyCyanService.deviceState == .connected
    }

    private func updateTimedGlassesAnalysis() {
        if canRunTimedGlassesAnalysis {
            startTimedGlassesAnalysisIfNeeded()
        } else {
            stopTimedGlassesAnalysis()
        }
    }

    private func restartTimedGlassesAnalysisIfNeeded() {
        guard timedGlassesAnalysisTask != nil else { return }
        stopTimedGlassesAnalysis()
        updateTimedGlassesAnalysis()
    }

    private func startTimedGlassesAnalysisIfNeeded() {
        guard timedGlassesAnalysisTask == nil else { return }
        timedGlassesAnalysisTask = Task { @MainActor in
            while !Task.isCancelled {
                await runTimedGlassesAnalysisOnce()

                let delay = max(5.0, glassesTimedAnalysisInterval)
                try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            }
        }
    }

    private func stopTimedGlassesAnalysis() {
        timedGlassesAnalysisTask?.cancel()
        timedGlassesAnalysisTask = nil
        isTimedGlassesAnalysisRunning = false
        timedGlassesAnalysisStatus = ""
        bluetoothManager.stopVibration()
    }

    private func runTimedGlassesAnalysisOnce() async {
        guard canRunTimedGlassesAnalysis,
              !isTimedGlassesAnalysisRunning else { return }

        isTimedGlassesAnalysisRunning = true
        defer { isTimedGlassesAnalysisRunning = false }

        timedGlassesAnalysisStatus = languageManager.text("capturing_glasses_photo")
        guard let image = await heyCyanService.captureCurrentGlassesFrame(),
              !Task.isCancelled else { return }
        lastTimedGlassesAnalysisAt = Date()

        guard LiberEyeCloudConfig.isEnabled && LiberEyeCloudConfig.isConfigured else {
            timedGlassesAnalysisStatus = "Configure and enable LiberEye Cloud."
            return
        }
        guard !liberEyeCloudService.isCallingCloud else { return }
        timedGlassesAnalysisStatus = languageManager.text("analyzing_glasses_photo")
        do {
            let plan = try await liberEyeCloudService.analyze(
                image: image, detailRequest: false,
                wristConnected: bluetoothManager.canDeliverFeedback
            )
            guard !Task.isCancelled else { return }
            dispatchCloudPlan(plan)
            timedGlassesAnalysisStatus = languageManager.text("timed_analysis_complete")
        } catch {
            guard !Task.isCancelled else { return }
            bluetoothManager.stopVibration()
            liberEyeCloudService.lastError = error.localizedDescription
            timedGlassesAnalysisStatus = "The cloud connection was interrupted. Pause and try again."
        }
    }

    private func dangerIcon(for level: DangerLevel) -> String {
        switch level {
        case .safe:     return "checkmark.shield.fill"
        case .low:      return "exclamationmark.circle"
        case .medium:   return "exclamationmark.triangle"
        case .high:     return "exclamationmark.triangle.fill"
        case .critical: return "xmark.octagon.fill"
        }
    }

    private func timeAgo(_ date: Date) -> String {
        let seconds = Int(Date().timeIntervalSince(date))
        if seconds < 5  { return languageManager.text("just_now") }
        if seconds < 60 { return languageManager.format("seconds_ago", seconds) }
        return languageManager.format("minutes_ago", seconds / 60)
    }
}

// MARK: - Device status capsule
struct DeviceStatusPill: View {
    let icon: String
    let label: String
    let state: DeviceConnectionState

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 12))
            Text(label)
                .font(.caption2)
                .fontWeight(.medium)
            Circle()
                .fill(state.color)
                .frame(width: 7, height: 7)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(
            Capsule()
                .fill(.ultraThinMaterial)
                .overlay(
                    Capsule()
                        .fill(state.color.opacity(0.08))
                )
                .overlay(
                    Capsule()
                        .stroke(Color.white.opacity(0.5), lineWidth: 1)
                )
        )
        .accessibilityLabel("\(label)\(state.displayText)")
    }
}

// MARK: - Primary action button with Liquid Glass styling
struct LargeActionButton: View {
    let icon: String
    let label: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 28, weight: .semibold))
                Text(label)
                    .font(.system(size: 17, weight: .semibold))
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 18)
            .padding(.bottom, 14)
            .foregroundColor(color)
            .glassActionButton(color: color)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}
