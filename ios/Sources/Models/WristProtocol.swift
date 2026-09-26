import Foundation

// MARK: - Haptic commands
nonisolated struct VibrationCommand {
    let pattern: VibrationPattern
    let duration: Int  // Milliseconds

    enum VibrationPattern: UInt8 {
        case stop = 0x00
        case d1 = 0x01          // Far approach: light 150 ms pulse every 2 seconds.
        case d2 = 0x02          // Medium approach: light 150 ms pulse every second.
        case d3 = 0x03          // Near approach: medium 200 ms pulse every 500 ms.
        case d4 = 0x04          // Very near: medium 200 ms pulse every 250 ms.
        case w1 = 0x05          // Hazard attention: two strong 250 ms pulses.
        case w2 = 0x06          // Immediate avoidance: two groups of three strong pulses.
        case w3 = 0x07          // Emergency stop: one strong 1-second pulse and four rapid pulses.

        var code: String {
            switch self {
            case .stop: return "STOP"
            case .d1: return "D1"
            case .d2: return "D2"
            case .d3: return "D3"
            case .d4: return "D4"
            case .w1: return "W1"
            case .w2: return "W2"
            case .w3: return "W3"
            }
        }
    }

    static let navigationTurn = VibrationCommand(pattern: .d2, duration: 1200)
    static let arrived = VibrationCommand(pattern: .w1, duration: 800)
    static let safeConfirm = VibrationCommand(pattern: .d1, duration: 800)
    static let hazardAttention = VibrationCommand(pattern: .w1, duration: 800)
    static let immediateAvoidance = VibrationCommand(pattern: .w2, duration: 2000)
    static let emergencyStop = VibrationCommand(pattern: .w3, duration: 2000)

    static func fromCloudPattern(_ pattern: String, duration: Int? = nil) -> VibrationCommand? {
        switch pattern.uppercased() {
        case "D1": return VibrationCommand(pattern: .d1, duration: duration ?? 3000)
        case "D2": return VibrationCommand(pattern: .d2, duration: duration ?? 3000)
        case "D3": return VibrationCommand(pattern: .d3, duration: duration ?? 3000)
        case "D4": return VibrationCommand(pattern: .d4, duration: duration ?? 3000)
        case "W1": return VibrationCommand(pattern: .w1, duration: duration ?? 3000)
        case "W2": return VibrationCommand(pattern: .w2, duration: duration ?? 3000)
        case "W3": return VibrationCommand(pattern: .w3, duration: duration ?? 3000)
        case "STOP": return VibrationCommand(pattern: .stop, duration: 0)
        default: return nil
        }
    }

    func toData() -> Data {
        var bytes: [UInt8] = [pattern.rawValue]
        let durationBytes = withUnsafeBytes(of: UInt16(max(0, min(duration, 8000))).bigEndian) { Array($0) }
        bytes.append(contentsOf: durationBytes)
        return Data(bytes)
    }
}

/// NUS notifications can split or combine newline-delimited firmware messages.
nonisolated struct WristStatusMessage: Equatable {
    enum Kind { case acknowledgement, event }
    let kind: Kind
    let code: UInt8
    let status: String
}

nonisolated struct WristStatusDecoder {
    private var buffer = ""

    mutating func append(_ data: Data) -> [WristStatusMessage] {
        guard let chunk = String(data: data, encoding: .utf8) else { buffer = ""; return [] }
        buffer += chunk
        guard buffer.utf8.count <= 256 else { buffer = ""; return [] }
        var messages: [WristStatusMessage] = []
        while let newline = buffer.firstIndex(of: "\n") {
            let line = String(buffer[..<newline]).trimmingCharacters(in: .whitespacesAndNewlines)
            buffer.removeSubrange(...newline)
            let parts = line.split(separator: " ")
            guard parts.count == 3, let code = UInt8(parts[1]), code <= 7 || code == 255 else { continue }
            let status = String(parts[2])
            if parts[0] == "ACK", ["ok", "refresh", "busy", "stopped", "invalid", "driver", "overflow"].contains(status) {
                messages.append(WristStatusMessage(kind: .acknowledgement, code: code, status: status))
            } else if parts[0] == "EVT", ["done", "timeout", "disconnect", "driver", "ready"].contains(status) {
                messages.append(WristStatusMessage(kind: .event, code: code, status: status))
            }
        }
        return messages
    }
}
