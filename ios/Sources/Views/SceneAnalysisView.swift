//
//  SceneAnalysisView.swift
//  LiberEye
//
//  Scene analysis view for text, scenes, and stores.
//

import SwiftUI
import PhotosUI

struct SceneAnalysisView: View {
    @EnvironmentObject var visionService: VisionService
    @EnvironmentObject var cameraManager: CameraManager
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var speechManager: SpeechManager
    @EnvironmentObject var languageManager: AppLanguageManager

    @StateObject private var heyCyanService = HeyCyanService.shared
    @StateObject private var liberEyeCloudService = LiberEyeCloudService.shared
    @State private var selectedMode: SceneAnalysisMode = .fullAnalysis
    @State private var selectedPhoto: PhotosPickerItem? = nil
    @State private var capturedImage: UIImage? = nil
    @State private var showImagePicker = false
    @State private var showCamera = false
    @State private var ocrText: String = ""
    @State private var isOCRRunning = false

    var body: some View {
        NavigationStack {
            ZStack {
                LGStyle.backgroundGradient.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 18) {
                        if !isConfigured {
                            configurationBanner
                        }

                        analysisModeSelector

                        imageSourceButtons

                        if let image = capturedImage {
                            imagePreview(image)
                        }

                        if let result = visionService.lastResult {
                            resultCard(result)
                        }

                        if let plan = liberEyeCloudService.lastPlan {
                            cloudPlanCard(plan)
                        }

                        if !ocrText.isEmpty {
                            quickOCRCard
                        }

                        if capturedImage == nil && visionService.lastResult == nil && ocrText.isEmpty {
                            quickFeatureTips
                        }
                    }
                    .padding(.horizontal)
                    .tabBarPadding()
                }
                .overlay {
                    if visionService.isAnalyzing || liberEyeCloudService.isCallingCloud || isOCRRunning {
                        analyzeLoadingOverlay
                    }
                }
            }
        }
        .navigationTitle(languageManager.text("scene_analysis"))
        .navigationBarTitleDisplayMode(.inline)
        .onChange(of: selectedPhoto) { _, item in
            Task {
                if let item = item,
                   let data = try? await item.loadTransferable(type: Data.self),
                   let image = UIImage(data: data) {
                    capturedImage = image
                    await analyzeImage(image)
                }
            }
        }
    }

    // MARK: - Configuration banner
    private var configurationBanner: some View {
        HStack(spacing: 10) {
            Image(systemName: "key.fill")
                .foregroundColor(.orange)
            VStack(alignment: .leading, spacing: 2) {
                Text(languageManager.text(LiberEyeCloudConfig.isEnabled ? "cloud_setup_required" : "need_doubao_api"))
                    .font(.subheadline)
                    .fontWeight(.semibold)
                Text(languageManager.text(LiberEyeCloudConfig.isEnabled ? "cloud_setup_description" : "need_doubao_api_desc"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.orange.opacity(0.1))
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.orange.opacity(0.3), lineWidth: 1))
        )
    }

    // MARK: - Analysis mode selection
    private var analysisModeSelector: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(languageManager.text("analysis_mode"))
                .font(.headline)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(SceneAnalysisMode.allCases, id: \.self) { mode in
                    ModeButton(
                        mode: mode,
                        isSelected: selectedMode == mode
                    ) {
                        selectedMode = mode
                        visionService.selectedMode = mode
                    }
                }
            }
        }
    }

    // MARK: - Image source buttons
    private var imageSourceButtons: some View {
        let albumTitle = languageManager.text("choose_from_album")
        return LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 14) {
            sourceActionButton(
                title: languageManager.text("take_photo_analysis"),
                icon: "iphone.gen3",
                color: .blue,
                isEnabled: isConfigured,
                disabledHint: configurationMessage,
                action: captureFromCamera
            )

            #if LIBEREYE_WITH_HEYCYAN
            sourceActionButton(
                title: languageManager.text("analyze_glasses_frame"),
                icon: "eyeglasses",
                color: .teal,
                isEnabled: isConfigured && heyCyanService.deviceState == .connected,
                disabledHint: isConfigured ? languageManager.text("connect_glasses_first") : configurationMessage,
                action: captureFromGlasses
            )
            #endif

            PhotosPicker(selection: $selectedPhoto, matching: .images) {
                sourceActionLabel(
                    title: albumTitle,
                    icon: "photo.on.rectangle.angled",
                    color: .purple
                )
            }
            .accessibilityLabel(albumTitle)
            .disabled(!isConfigured)
            .opacity(isConfigured ? 1 : 0.45)

            sourceActionButton(
                title: languageManager.text("quick_ocr"),
                icon: "doc.text.viewfinder",
                color: .green,
                action: quickCaptureOCR
            )
        }
    }

    private func sourceActionButton(
        title: String,
        icon: String,
        color: Color,
        isEnabled: Bool = true,
        disabledHint: String? = nil,
        action: @escaping () -> Void
    ) -> some View {
        Button {
            if isEnabled {
                action()
            } else if let disabledHint {
                speechManager.speak(disabledHint, priority: .normal)
            }
        } label: {
            sourceActionLabel(title: title, icon: icon, color: color)
                .opacity(isEnabled ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
    }

    private func sourceActionLabel(title: String, icon: String, color: Color) -> some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 40, weight: .semibold))
            Text(title)
                .font(.system(size: 18, weight: .semibold))
                .multilineTextAlignment(.center)
                .lineLimit(2)
                .minimumScaleFactor(0.78)
        }
        .frame(maxWidth: .infinity)
        .frame(height: 128)
        .glassActionButton(color: color)
        .foregroundColor(color)
    }

    // MARK: - Image preview
    private func imagePreview(_ image: UIImage) -> some View {
        VStack(spacing: 8) {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .frame(maxHeight: 200)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .shadow(radius: 4)

            HStack {
                Button(action: {
                    capturedImage = nil
                    visionService.lastResult = nil
                    liberEyeCloudService.lastPlan = nil
                    ocrText = ""
                }) {
                    Label(languageManager.text("clear"), systemImage: "trash")
                        .font(.caption)
                        .foregroundColor(.red)
                }

                Spacer()

                Button(action: { Task { await analyzeImage(image) } }) {
                    Label(languageManager.text("reanalyze"), systemImage: "arrow.clockwise")
                        .font(.caption)
                        .foregroundColor(.blue)
                }
            }
            .padding(.horizontal, 4)
        }
    }

    // MARK: - Analysis result card
    private func resultCard(_ result: SceneAnalysisResult) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: result.mode.icon)
                    .foregroundColor(.purple)
                Text("\(result.mode.displayName) \(languageManager.text("result_suffix"))")
                    .font(.headline)
                Spacer()
                Text(String(format: "%.1fs", result.processingTime))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Divider()

            Text(result.content)
                .font(.system(size: 16))
                .lineSpacing(4)

            Button(action: {
                speechManager.speakAnalysisResult(result)
            }) {
                HStack {
                    Image(systemName: "speaker.wave.3.fill")
                        .symbolEffect(.variableColor, options: .repeating,
                                      value: speechManager.isSpeaking)
                    Text(speechManager.isSpeaking ? languageManager.text("speaking") : languageManager.text("voice_result"))
                        .fontWeight(.medium)
                    Spacer()
                }
                .padding()
                .glassActionButton(color: .purple)
                .foregroundColor(.purple)
            }
            .buttonStyle(.plain)
        }
        .padding()
        .glassCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(languageManager.text("analysis_result")): \(result.content)")
    }

    // MARK: - Quick OCR results
    private var quickOCRCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: "doc.text.fill")
                    .foregroundColor(.green)
                Text(languageManager.text("recognized_text"))
                    .font(.headline)
                Spacer()
                Button(action: {
                    speechManager.speak(ocrText, priority: .normal)
                }) {
                    Image(systemName: "speaker.wave.2.fill")
                        .foregroundColor(.green)
                }
                .accessibilityLabel(languageManager.text("speak_recognized_text"))
            }

            Text(ocrText)
                .font(.system(size: 15))
                .lineSpacing(3)
        }
        .padding()
        .glassCard()
        .overlay(
            RoundedRectangle(cornerRadius: LGStyle.cardCornerRadius)
                .stroke(Color.green.opacity(0.25), lineWidth: 1)
        )
    }

    // MARK: - Usage tips
    private var quickFeatureTips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(languageManager.text("usage_tips"))
                .font(.subheadline)
                .foregroundColor(.secondary)

            VStack(alignment: .leading, spacing: 6) {
                tipRow(icon: "storefront", text: languageManager.text("tip_store"))
                tipRow(icon: "doc.text", text: languageManager.text("tip_text"))
                tipRow(icon: "exclamationmark.triangle", text: languageManager.text("tip_obstacle"))
                tipRow(icon: "doc.text.viewfinder", text: languageManager.text("tip_quick_ocr"))
            }
            .padding()
            .glassCard()
        }
    }

    private func tipRow(icon: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 13))
                .foregroundColor(.blue)
                .frame(width: 18)
            Text(text)
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }

    // MARK: - Loading overlay
    private var analyzeLoadingOverlay: some View {
        ZStack {
            Color.black.opacity(0.4)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                ProgressView()
                    .scaleEffect(1.5)
                    .tint(.white)
                Text(isOCRRunning ? languageManager.text("ocr_running") : languageManager.text("analyzing"))
                    .font(.headline)
                    .foregroundColor(.white)
                Text(languageManager.text("please_wait"))
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.7))
            }
            .padding(30)
            .background(RoundedRectangle(cornerRadius: 20).fill(Color(uiColor: .systemGray).opacity(0.9)))
        }
    }

    // MARK: - Computed helpers
    private var isConfigured: Bool {
        LiberEyeCloudConfig.isEnabled ? LiberEyeCloudConfig.isConfigured : DoubaoConfig.isConfigured
    }

    private var configurationMessage: String {
        languageManager.text(LiberEyeCloudConfig.isEnabled ? "cloud_setup_description" : "need_doubao_api_desc")
    }

    // MARK: - Actions
    private func captureFromCamera() {
        Task {
            if let image = await capturePhoneCameraFrame() {
                capturedImage = image
                await analyzeImage(image)
            } else {
                speechManager.speak("The phone camera is unavailable. Check camera permissions.", priority: .normal)
            }
        }
    }

    private func quickCaptureOCR() {
        Task {
            isOCRRunning = true
            ocrText = ""
            if let image = await capturePhoneCameraFrame() {
                capturedImage = image
                let text = await visionService.quickOCR(image: image)
                ocrText = text
                speechManager.speak(text.isEmpty ? languageManager.text("no_text_recognized") : text, priority: .normal)
            } else {
                speechManager.speak("The phone camera is unavailable. Check camera permissions.", priority: .normal)
            }
            isOCRRunning = false
        }
    }

    private func captureFromGlasses() {
        Task {
            if let image = await heyCyanService.captureCurrentGlassesFrame() {
                capturedImage = image
                await analyzeImage(image)
            } else {
                speechManager.speak(languageManager.text("no_glasses_frame"), priority: .normal)
            }
        }
    }

    private func capturePhoneCameraFrame() async -> UIImage? {
        if cameraManager.authorizationStatus != .authorized {
            await cameraManager.checkPermissions()
        }
        if !cameraManager.isRunning {
            cameraManager.startSession()
            try? await Task.sleep(nanoseconds: 450_000_000)
        }
        return await cameraManager.capturePhotoAsync()
    }

    private func analyzeImage(_ image: UIImage) async {
        guard isConfigured else {
            speechManager.speak(configurationMessage, priority: .normal)
            return
        }
        ocrText = ""
        visionService.lastResult = nil
        liberEyeCloudService.lastPlan = nil

        if LiberEyeCloudConfig.isEnabled {
            do {
                let plan = try await liberEyeCloudService.analyze(
                    image: image, targetQuery: selectedMode.userPrompt, detailRequest: true,
                    wristConnected: bluetoothManager.canDeliverFeedback
                )
                dispatchCloudPlan(plan)
                return
            } catch {
                if error is CancellationError { return }
                bluetoothManager.stopVibration()
                let message = "LiberEye Cloud analysis failed: \(error.localizedDescription)"
                liberEyeCloudService.lastError = message
                speechManager.speak(message, priority: .normal)
                return
            }
        }

        await visionService.analyze(image: image, mode: selectedMode)
        if let result = visionService.lastResult {
            speechManager.speakAnalysisResult(result)
        } else if let error = visionService.error {
            speechManager.speak(error, priority: .normal)
        }
    }

    private func dispatchCloudPlan(_ plan: LiberEyeCloudPlan) {
        RelayOutputCoordinator.dispatch(plan, bluetooth: bluetoothManager, speech: speechManager)
    }

    private func cloudPlanCard(_ plan: LiberEyeCloudPlan) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "cloud.fill")
                    .foregroundColor(.teal)
                Text(languageManager.text("cloud_result"))
                    .font(.headline)
                Spacer()
                Text(languageManager.text(plan.priority == "danger" ? "cloud_priority_danger" : plan.priority == "warn" ? "cloud_priority_warn" : "cloud_priority_normal"))
                    .font(.caption)
                    .fontWeight(.bold)
                    .foregroundColor(plan.priority == "danger" ? .red : plan.priority == "warn" ? .orange : .green)
            }

            Divider()

            Text(plan.displayText)
                .font(.system(size: 16))
                .lineSpacing(4)

            if let bracelet = plan.bracelet {
                Label(bracelet.meaning ?? languageManager.text("bracelet"), systemImage: "applewatch")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .glassCard()
    }
}

// MARK: - Analysis mode button
struct ModeButton: View {
    let mode: SceneAnalysisMode
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: mode.icon)
                    .font(.system(size: 22))
                Text(mode.displayName)
                    .font(.system(size: 18, weight: .semibold))
                Spacer()
            }
            .padding(.horizontal, 14)
            .frame(height: 64)
            .background(
                Group {
                    if isSelected {
                        RoundedRectangle(cornerRadius: 12)
                            .fill(Color.purple)
                            .shadow(color: .purple.opacity(0.2), radius: 3)
                    } else {
                        RoundedRectangle(cornerRadius: 12)
                            .fill(.ultraThinMaterial)
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(Color.white.opacity(0.5), lineWidth: 1)
                            )
                            .shadow(color: .black.opacity(0.05), radius: 3)
                    }
                }
            )
            .foregroundColor(isSelected ? .white : .primary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(mode.displayName)
    }
}
