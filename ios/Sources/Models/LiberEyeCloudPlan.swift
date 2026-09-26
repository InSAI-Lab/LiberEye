import Foundation

struct LiberEyeCloudPlan: Codable {
    let source: String?
    let priority: String
    let mainInstruction: String
    let secondaryInstruction: String?
    let voiceMessage: String
    let sceneBrief: String?
    let riskBrief: String?
    let nextAction: String?
    let bracelet: LiberEyeCloudBracelet?
    let outputActions: [LiberEyeCloudAction]
    let shouldSpeak: Bool?
    let sceneType: String?
    let visionBackend: String?
    let wristCue: String?
    let descriptionGate: Bool?
    let descriptionBlocked: Bool?
    let actionInstruction: String?
    let eligibleSceneDescription: String?

    enum CodingKeys: String, CodingKey {
        case source
        case priority
        case mainInstruction = "main_instruction"
        case secondaryInstruction = "secondary_instruction"
        case voiceMessage = "voice_message"
        case sceneBrief = "scene_brief"
        case riskBrief = "risk_brief"
        case nextAction = "next_action"
        case bracelet
        case outputActions = "output_actions"
        case shouldSpeak = "should_speak"
        case sceneType = "scene_type"
        case visionBackend = "vision_backend"
        case wristCue = "wrist_cue"
        case descriptionGate = "description_gate"
        case descriptionBlocked = "description_blocked"
        case actionInstruction = "action_instruction"
        case eligibleSceneDescription = "eligible_scene_description"
    }

    var authorizedSpeechActions: [LiberEyeCloudAction] {
        guard shouldSpeak == true else { return [] }
        return outputActions.filter { $0.type == "tts" && !($0.message ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    var authorizedHapticCommand: VibrationCommand? {
        guard let action = outputActions.first(where: { $0.type == "ble_haptic" }),
              let pattern = action.pattern,
              action.protocolName == nil || action.protocolName == "libereye-wrist-v1",
              let command = VibrationCommand.fromCloudPattern(pattern, duration: action.durationMs) else { return nil }
        if let bytes = action.commandBytes, Data(bytes) != command.toData() { return nil }
        return command
    }

    var displayText: String {
        var parts: [String] = []
        if let sceneBrief, !sceneBrief.isEmpty {
            parts.append("Scene: \(sceneBrief)")
        }
        if let riskBrief, !riskBrief.isEmpty {
            parts.append("Risk: \(riskBrief)")
        }
        if let nextAction, !nextAction.isEmpty {
            parts.append("Next action: \(nextAction)")
        }
        if parts.isEmpty {
            parts.append(mainInstruction)
        }
        if let bracelet {
            parts.append("Wrist cue \(bracelet.pattern): \(bracelet.meaning ?? "Haptic feedback")")
        }
        return parts.joined(separator: "\n")
    }
}

struct LiberEyeCloudBracelet: Codable {
    let device: String?
    let pattern: String
    let frequencyHz: Double?
    let intensity: Int
    let riskLevel: String?
    let meaning: String?

    enum CodingKeys: String, CodingKey {
        case device
        case pattern
        case frequencyHz = "frequency_hz"
        case intensity
        case riskLevel = "risk_level"
        case meaning
    }
}

struct LiberEyeCloudAction: Codable {
    let type: String
    let message: String?
    let priority: String?
    let interrupt: Bool?
    let device: String?
    let pattern: String?
    let intensity: Int?
    let riskLevel: String?
    let meaning: String?
    let command: String?
    let protocolName: String?
    let commandBytes: [UInt8]?
    let durationMs: Int?
    let mainInstruction: String?
    let secondaryInstruction: String?

    enum CodingKeys: String, CodingKey {
        case type
        case message
        case priority
        case interrupt
        case device
        case pattern
        case intensity
        case riskLevel = "risk_level"
        case meaning
        case command
        case protocolName = "protocol"
        case commandBytes = "command_bytes"
        case durationMs = "duration_ms"
        case mainInstruction = "main_instruction"
        case secondaryInstruction = "secondary_instruction"
    }
}
