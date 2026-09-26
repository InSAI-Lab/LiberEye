//
//  SpeechManager.swift
//  LiberEye
//
//  Text-to-speech guidance
//

import Foundation
import AVFoundation
import Combine
import SwiftUI

@MainActor
class SpeechManager: NSObject, ObservableObject {

    @Published var isSpeaking: Bool = false
    var prepareExternalPlayback: (() -> Void)?

    private let synthesizer = AVSpeechSynthesizer()
    private var currentText = ""
    private var currentPriority: SpeechPriority = .normal

    enum SpeechPriority: Int, Comparable {
        case low = 0
        case normal = 1
        case high = 2      // Danger warnings
        case critical = 3  // Emergency guidance

        static func < (lhs: SpeechPriority, rhs: SpeechPriority) -> Bool {
            lhs.rawValue < rhs.rawValue
        }
    }

    override init() {
        super.init()
        synthesizer.delegate = self
        configureAudioSession()
    }

    private func configureAudioSession() {
        try? AVAudioSession.sharedInstance().setCategory(
            .playback,
            mode: .spokenAudio,
            options: [.duckOthers, .allowBluetoothA2DP]
        )
        try? AVAudioSession.sharedInstance().setActive(true)
    }

    // MARK: - Speaking text
    func speak(_ text: String,
               priority: SpeechPriority = .normal,
               rate: Float? = nil,
               interruptIfNeeded: Bool = false) {

        guard !text.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        guard !(synthesizer.isSpeaking && (text == currentText || priority < currentPriority)) else { return }
        currentText = text
        prepareExternalPlayback?()

        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = clampedRate(rate ?? preferredSpeechRate)
        utterance.pitchMultiplier = 1.0
        utterance.volume = 1.0

        // Interrupt for urgent guidance or an explicit request.
        if interruptIfNeeded || priority >= .high {
            synthesizer.stopSpeaking(at: .immediate)
        }

        synthesizer.speak(utterance)
        isSpeaking = true
        currentPriority = priority
    }

    // MARK: - High-priority obstacle warnings
    func speakObstacleAlert(_ obstacle: ObstacleInfo) {
        let text: String
        switch obstacle.dangerLevel {
        case .critical:
            text = "Stop immediately! \(obstacle.description) is \(String(format: "%.0f", obstacle.distance * 100)) centimeters \(obstacle.direction)."
        case .high:
            text = "Danger! \(obstacle.voiceAlert)"
        case .medium:
            text = "Caution. \(obstacle.voiceAlert)"
        case .low:
            text = "There is \(obstacle.description) \(obstacle.direction)."
        case .safe:
            return
        }

        let priority: SpeechPriority = obstacle.dangerLevel >= .high ? .critical : .high
        let alertRate = obstacle.dangerLevel >= .high ? max(preferredSpeechRate, 0.78) : preferredSpeechRate
        speak(text, priority: priority, rate: alertRate,
              interruptIfNeeded: obstacle.dangerLevel >= .high)
    }

    // MARK: - Stopping speech
    func stopSpeaking() {
        synthesizer.stopSpeaking(at: .immediate)
        currentText = ""
        currentPriority = .normal
        isSpeaking = false
    }

    // MARK: - Heading announcements
    func speakDirection(_ direction: CompassDirection) {
        speak("Facing \(direction.rawValue).", priority: .normal)
    }

    // MARK: - Analysis announcements
    func speakAnalysisResult(_ result: SceneAnalysisResult) {
        speak(result.voiceText, priority: .normal, rate: max(preferredSpeechRate, 0.78))
    }

    private var preferredSpeechRate: Float {
        let saved = UserDefaults.standard.object(forKey: "speech_rate") as? Double ?? 0.72
        return clampedRate(Float(saved))
    }

    private func clampedRate(_ rate: Float) -> Float {
        min(max(rate, AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
    }
}

// MARK: - AVSpeechSynthesizerDelegate
extension SpeechManager: AVSpeechSynthesizerDelegate {

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                        didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            isSpeaking = self.synthesizer.isSpeaking
        }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                        didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in
            isSpeaking = self.synthesizer.isSpeaking
        }
    }
}
