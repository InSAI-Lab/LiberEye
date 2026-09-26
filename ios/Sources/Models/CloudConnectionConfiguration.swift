import Foundation

nonisolated enum LiberEyeCloudError: Error, LocalizedError {
    case invalidURL
    case endpointURL
    case invalidToken
    case notConfigured
    case credentialStorageFailed
    case busy
    case imageEncodingFailed
    case invalidResponse
    case serverError(Int, String)

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "Enter the cloud HTTPS address and access token in Settings"
        case .credentialStorageFailed:
            return "The access token could not be saved to Keychain. Unlock the device and try again"
        case .invalidURL:
            return "Enter a valid HTTPS base address without credentials, query parameters or a fragment"
        case .endpointURL:
            return "Enter the cloud base address without /ready, /health or /api/mobile/analyze-media"
        case .invalidToken:
            return "The access token cannot contain spaces or control characters"
        case .busy:
            return "The previous frame is still being analyzed. Try again shortly"
        case .imageEncodingFailed:
            return "Image compression failed"
        case .invalidResponse:
            return "The cloud response is invalid. Check that the address points to a LiberEye service"
        case .serverError(let code, let message):
            return "Cloud error \(code): \(message)"
        }
    }
}

/// A validated server prefix and credential used together for each request.
nonisolated struct LiberEyeCloudConnection: Equatable {
    let baseURL: URL
    let apiToken: String

    init(baseURL: String, apiToken: String, allowsInsecureHTTP: Bool = false) throws {
        let address = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let token = apiToken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !address.isEmpty, !token.isEmpty else { throw LiberEyeCloudError.notConfigured }
        guard token.unicodeScalars.allSatisfy({ $0.value > 32 && $0.value < 127 }) else {
            throw LiberEyeCloudError.invalidToken
        }
        guard let components = URLComponents(string: address),
              let host = components.host, !host.isEmpty,
              !host.unicodeScalars.contains(where: CharacterSet.whitespacesAndNewlines.contains),
              components.user == nil, components.password == nil,
              components.query == nil, components.fragment == nil,
              let scheme = components.scheme?.lowercased(),
              scheme == "https" || (scheme == "http" && allowsInsecureHTTP),
              components.port.map({ (1...65535).contains($0) }) ?? true,
              let url = components.url else { throw LiberEyeCloudError.invalidURL }
        let path = components.path.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if ["ready", "health", "api/mobile/analyze-media", "api/mobile/analyze-perception"].contains(where: {
            path == $0 || path.hasSuffix("/" + $0)
        }) {
            throw LiberEyeCloudError.endpointURL
        }
        self.baseURL = url
        self.apiToken = token
    }

    func request(path: String, method: String = "GET", sessionID: String? = nil) -> URLRequest {
        let suffix = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        var request = URLRequest(url: baseURL.appendingPathComponent(suffix))
        request.httpMethod = method
        request.setValue("Bearer \(apiToken)", forHTTPHeaderField: "Authorization")
        if let sessionID { request.setValue(sessionID, forHTTPHeaderField: "X-LiberEye-Session") }
        return request
    }
}

nonisolated enum LiberEyePerceptionMode: String, Decodable {
    case model
    case heuristic
}

nonisolated struct LiberEyeCloudReadiness: Decodable {
    let status: String
    let perceptionMode: LiberEyePerceptionMode

    enum CodingKeys: String, CodingKey {
        case status
        case perceptionMode = "perception_mode"
    }

    static func decode(_ data: Data, statusCode: Int) throws -> Self {
        try LiberEyeCloudResponse.checkStatus(statusCode, data: data)
        guard let readiness = try? JSONDecoder().decode(Self.self, from: data),
              readiness.status == "ready" else { throw LiberEyeCloudError.invalidResponse }
        return readiness
    }
}

nonisolated enum LiberEyeCloudResponse {
    static func checkStatus(_ code: Int, data: Data) throws {
        guard code != 200 else { return }
        let message: String
        switch code {
        case 401, 403:
            message = "The access token is invalid or access was denied. Check the token in Settings"
        case 413:
            message = "The image exceeds the server size limit"
        case 422:
            message = "The server could not process this image or the request parameters"
        case 429:
            message = "Too many requests. Try again shortly"
        case 503:
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if let detail = body?["detail"] as? String, detail.lowercased().contains("busy") {
                message = "The vision service is busy with another request. Try again shortly"
            } else {
                message = "The service is not ready. Check the server model files and configuration"
            }
        default:
            message = "The request failed. Check the server address and service status"
        }
        throw LiberEyeCloudError.serverError(code, message)
    }
}
