import Foundation

@main
struct RelayContractTests {
    static func main() throws {
        try testCloudConnection()
        let decoder = JSONDecoder()
        func plan(_ extra: String) throws -> LiberEyeCloudPlan {
            let json = """
            {"priority":"normal", "main_instruction":"Continue", "voice_message":"Do not speak this fallback", \(extra)}
            """
            return try decoder.decode(LiberEyeCloudPlan.self, from: Data(json.utf8))
        }
        let gated = try plan("\"should_speak\":false,\"output_actions\":[{\"type\":\"tts\",\"message\":\"Blocked\"}]")
        precondition(gated.authorizedSpeechActions.isEmpty, "Gated speech must be suppressed")
        let unspecifiedSpeech = try plan("\"output_actions\":[{\"type\":\"tts\",\"message\":\"Not authorized\"}]")
        precondition(unspecifiedSpeech.authorizedSpeechActions.isEmpty, "Speech requires explicit cloud authorization")
        let noSpeech = try plan("\"should_speak\":true,\"output_actions\":[]")
        precondition(noSpeech.authorizedSpeechActions.isEmpty, "voice_message must not act as an implicit TTS command")
        precondition(noSpeech.authorizedHapticCommand == nil, "No haptic action means stop the previous lease")
        let d1 = try plan("\"bracelet\":{\"pattern\":\"D1\",\"intensity\":1,\"frequency_hz\":0.5},\"output_actions\":[{\"type\":\"ble_haptic\",\"pattern\":\"D1\",\"duration_ms\":3000}]")
        precondition(d1.bracelet?.frequencyHz == 0.5, "D1 is 0.5 Hz")
        precondition(d1.authorizedHapticCommand?.toData() == Data([1, 0x0B, 0xB8]), "Wire lease must be big endian")
        let wristV1 = try plan("\"output_actions\":[{\"type\":\"ble_haptic\",\"pattern\":\"D1\",\"duration_ms\":3000,\"protocol\":\"libereye-wrist-v1\",\"command_bytes\":[1,11,184]}]")
        precondition(wristV1.authorizedHapticCommand?.toData() == Data([1, 11, 184]))
        let mismatchedBytes = try plan("\"output_actions\":[{\"type\":\"ble_haptic\",\"pattern\":\"D1\",\"duration_ms\":3000,\"command_bytes\":[7,11,184]}]")
        precondition(mismatchedBytes.authorizedHapticCommand == nil, "Inconsistent cloud wire bytes must not reach the wrist")
        let unsupportedProtocol = try plan("\"output_actions\":[{\"type\":\"ble_haptic\",\"pattern\":\"D1\",\"protocol\":\"unknown\"}]")
        precondition(unsupportedProtocol.authorizedHapticCommand == nil)
        precondition(VibrationCommand.fromCloudPattern("W3", duration: 3000)?.toData() == Data([7, 0x0B, 0xB8]))
        for (index, name) in ["STOP", "D1", "D2", "D3", "D4", "W1", "W2", "W3"].enumerated() {
            precondition(VibrationCommand.fromCloudPattern(name)?.toData().first == UInt8(index))
        }
        precondition(VibrationCommand(pattern: .d2, duration: -1).toData() == Data([2, 0, 0]))
        precondition(VibrationCommand(pattern: .d2, duration: 100_000).toData() == Data([2, 0x1F, 0x40]))
        precondition(VibrationCommand.fromCloudPattern("UNKNOWN") == nil)
        let warning = try plan("\"should_speak\":true,\"output_actions\":[{\"type\":\"tts\",\"message\":\"Stop\",\"priority\":\"danger\"}]")
        precondition(warning.authorizedSpeechActions.count == 1)
        var statusDecoder = WristStatusDecoder()
        precondition(statusDecoder.append(Data("ACK 1 re".utf8)).isEmpty)
        let statuses = statusDecoder.append(Data("fresh\nEVT 1 timeout\n".utf8))
        precondition(statuses == [WristStatusMessage(kind: .acknowledgement, code: 1, status: "refresh"),
                                  WristStatusMessage(kind: .event, code: 1, status: "timeout")])
        precondition(statusDecoder.append(Data("ACK 8 ok\nACK 1 unknown\n".utf8)).isEmpty)
        precondition(statusDecoder.append(Data(repeating: 65, count: 300)).isEmpty)
        precondition(statusDecoder.append(Data("ACK 255 invalid\n".utf8)).first?.code == 255)
        print("PASS: cloud URL and authentication contract, readiness responses, relay speech gating, wrist protocol validation and fragmented firmware acknowledgements")
    }

    private static func testCloudConnection() throws {
        for base in ["https://libereye.example.org", "https://libereye.example.org/"] {
            let connection = try LiberEyeCloudConnection(baseURL: base, apiToken: " test-token ")
            let ready = connection.request(path: "ready")
            precondition(ready.url?.absoluteString == "https://libereye.example.org/ready")
            precondition(ready.value(forHTTPHeaderField: "Authorization") == "Bearer test-token")
            precondition(ready.httpMethod == "GET")
        }
        let prefix = try LiberEyeCloudConnection(baseURL: "https://libereye.example.org/mobility/", apiToken: "token")
        let request = prefix.request(path: "/api/mobile/analyze-media/", method: "POST", sessionID: "session-123")
        precondition(request.url?.absoluteString == "https://libereye.example.org/mobility/api/mobile/analyze-media")
        precondition(request.value(forHTTPHeaderField: "X-LiberEye-Session") == "session-123")
        for invalid in ["", "libereye.example.org", "http://libereye.example.org", "https://user:pass@libereye.example.org", "https://libereye.example.org?token=x", "https://libereye.example.org#ready", "https://libereye.example.org:0", "https://libereye.example.org:65536", "https://libereye.example.org/api/mobile/analyze-media", "https://libereye.example.org/prefix/ready/"] {
            expectFailure { _ = try LiberEyeCloudConnection(baseURL: invalid, apiToken: "token") }
        }
        for token in ["", "invalid token", "line\nbreak", "control\u{7}"] {
            expectFailure { _ = try LiberEyeCloudConnection(baseURL: "https://libereye.example.org", apiToken: token) }
        }
        _ = try LiberEyeCloudConnection(baseURL: "http://127.0.0.1:8080", apiToken: "token", allowsInsecureHTTP: true)
        let model = try LiberEyeCloudReadiness.decode(Data(#"{"status":"ready","perception_mode":"model"}"#.utf8), statusCode: 200)
        precondition(model.perceptionMode == .model)
        let heuristic = try LiberEyeCloudReadiness.decode(Data(#"{"status":"ready","perception_mode":"heuristic"}"#.utf8), statusCode: 200)
        precondition(heuristic.perceptionMode == .heuristic)
        for invalid in [#"{"status":"ok","perception_mode":"model"}"#, #"{"status":"ready"}"#, #"{"status":"ready","perception_mode":"unknown"}"#, "<html>Service is running</html>"] {
            expectFailure { _ = try LiberEyeCloudReadiness.decode(Data(invalid.utf8), statusCode: 200) }
        }
        for code in [401, 403, 404, 503] {
            expectFailure { _ = try LiberEyeCloudReadiness.decode(Data(#"{"detail":{"message":"Required perception models unavailable","missing":["tactile"]}}"#.utf8), statusCode: code) }
        }
    }

    private static func expectFailure(_ operation: () throws -> Void) {
        do {
            try operation()
            preconditionFailure("Expected invalid cloud configuration or response to fail")
        } catch {}
    }
}
