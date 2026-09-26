//
//  VoiceAssistantManager.swift
//  LiberEye
//
//  Foreground wake-word and voice-command recognition
//

import Foundation
import AVFoundation
import AudioToolbox
import Combine
import Speech
import UIKit

@MainActor
final class VoiceAssistantManager: ObservableObject {

    let objectWillChange = ObservableObjectPublisher()

    @Published var isListening = false
    @Published var isAwake = false
    @Published var transcript = ""
    @Published var error: String?

    private var recognizer: SFSpeechRecognizer?
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var onCommand: ((String) -> Void)?
    private var awakeUntil: Date?
    private var lastHandledText = ""
    private var restartTask: Task<Void, Never>?
    private var mutedUntil: Date?
    private var lastWakeFeedbackAt: Date?

    private let wakeWords = ["LiberEye", "Liber Eye"]
    private let quickCommandWords = ["describe", "read", "scene", "around", "recognize"]

    func start(onCommand: @escaping (String) -> Void) {
        self.onCommand = onCommand

        guard !isListening else { return }

        let locale = "en_US"
        recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale))

        SFSpeechRecognizer.requestAuthorization { [weak self] speechStatus in
            AVAudioSession.sharedInstance().requestRecordPermission { micGranted in
                Task { @MainActor in
                    guard let self else { return }

                    guard speechStatus == .authorized else {
                        self.error = "Speech recognition permission is disabled"
                        return
                    }

                    guard micGranted else {
                        self.error = "Microphone permission is disabled"
                        return
                    }

                    self.startRecognition()
                }
            }
        }
    }

    func stop() {
        restartTask?.cancel()
        restartTask = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest?.endAudio()
        recognitionRequest = nil

        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }

        isListening = false
        isAwake = false
        awakeUntil = nil
    }

    func muteTemporarily(seconds: TimeInterval) {
        mutedUntil = Date().addingTimeInterval(seconds)
    }

    func clearTemporaryMute() {
        mutedUntil = nil
    }

    private func startRecognition() {
        stopCurrentRecognitionTask()

        do {
            let audioSession = AVAudioSession.sharedInstance()
            try audioSession.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .allowBluetoothHFP, .defaultToSpeaker])
            try audioSession.setActive(true, options: .notifyOthersOnDeactivation)

            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            recognitionRequest = request

            let inputNode = audioEngine.inputNode
            let recordingFormat = inputNode.inputFormat(forBus: 0)
            guard isValidAudioFormat(recordingFormat) else {
                self.error = "The microphone audio format is unavailable; retrying"
                restartRecognitionSoon(delay: 700_000_000)
                return
            }

            inputNode.removeTap(onBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
                request.append(buffer)
            }

            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
            error = nil

            recognitionTask = recognizer?.recognitionTask(with: request) { [weak self] result, taskError in
                Task { @MainActor in
                    self?.handleRecognition(result: result, error: taskError)
                }
            }
        } catch {
            self.error = "Could not start voice recognition: \(error.localizedDescription)"
            stop()
        }
    }

    private func isValidAudioFormat(_ format: AVAudioFormat) -> Bool {
        format.sampleRate > 0 && format.channelCount > 0
    }

    private func stopCurrentRecognitionTask() {
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest?.endAudio()
        recognitionRequest = nil

        if audioEngine.isRunning {
            audioEngine.stop()
        }
        audioEngine.inputNode.removeTap(onBus: 0)
    }

    private func handleRecognition(result: SFSpeechRecognitionResult?, error: Error?) {
        if let error {
            self.error = error.localizedDescription
            restartRecognitionSoon()
            return
        }

        guard let result else { return }

        let text = result.bestTranscription.formattedString
        transcript = text

        if let mutedUntil, Date() < mutedUntil {
            if wakeRange(in: normalized(text)) != nil {
                clearTemporaryMute()
            } else {
                return
            }
        }

        handlePartialWakeText(text)

        if result.isFinal {
            handleFinalText(text)
            restartRecognitionSoon()
        }
    }

    private func restartRecognitionSoon(delay: UInt64 = 350_000_000) {
        restartTask?.cancel()
        stopCurrentRecognitionTask()
        isListening = false

        restartTask = Task { @MainActor in
            try? await Task.sleep(nanoseconds: delay)
            guard !Task.isCancelled else { return }
            startRecognition()
        }
    }

    private func handleFinalText(_ rawText: String) {
        let text = normalized(rawText)
        guard !text.isEmpty, text != lastHandledText else { return }
        lastHandledText = text

        if let wakeRange = wakeRange(in: text) {
            isAwake = true
            awakeUntil = Date().addingTimeInterval(18)

            let command = text[wakeRange.upperBound...]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if command.isEmpty {
                onCommand?("")
            } else {
                onCommand?(command)
            }
            return
        }

        if isAwake, let awakeUntil, Date() <= awakeUntil {
            self.awakeUntil = Date().addingTimeInterval(18)
            onCommand?(text)
        } else {
            isAwake = false
        }
    }

    private func handlePartialWakeText(_ rawText: String) {
        let text = normalized(rawText)
        guard !text.isEmpty else { return }

        if let wakeRange = wakeRange(in: text) {
            isAwake = true
            awakeUntil = Date().addingTimeInterval(18)
            playWakeFeedbackIfNeeded()

            let command = text[wakeRange.upperBound...]
                .trimmingCharacters(in: .whitespacesAndNewlines)
            dispatchQuickCommandIfReady(command, fullText: text)
            return
        }

        if isAwake, let awakeUntil, Date() <= awakeUntil {
            self.awakeUntil = Date().addingTimeInterval(18)
            dispatchQuickCommandIfReady(text, fullText: text)
        } else {
            isAwake = false
        }
    }

    private func dispatchQuickCommandIfReady(_ command: String, fullText: String) {
        guard !command.isEmpty,
              fullText != lastHandledText,
              quickCommandWords.contains(where: { command.localizedCaseInsensitiveContains($0) }) else {
            return
        }

        lastHandledText = fullText
        onCommand?(command)
    }

    private func playWakeFeedbackIfNeeded() {
        if let lastWakeFeedbackAt, Date().timeIntervalSince(lastWakeFeedbackAt) < 2 {
            return
        }

        lastWakeFeedbackAt = Date()
        AudioServicesPlaySystemSound(1104)
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }

    private func wakeRange(in text: String) -> Range<String.Index>? {
        for wakeWord in wakeWords {
            if let range = text.range(of: wakeWord, options: [.caseInsensitive]) {
                return range
            }
        }
        return nil
    }

    private func normalized(_ text: String) -> String {
        text
            .replacingOccurrences(of: ",", with: " ")
            .replacingOccurrences(of: ".", with: " ")
            .replacingOccurrences(of: "?", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
