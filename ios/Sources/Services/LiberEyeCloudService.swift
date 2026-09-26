//
//  LiberEyeCloudService.swift
//  LiberEye
//
//  Cloud perception and mobility coordination client.
//

import Foundation
import Combine
import UIKit

@MainActor
enum LiberEyeCloudConfig {
    static var baseURL: String {
        get {
            let saved = UserDefaults.standard.string(forKey: "libereye_cloud_base_url")?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return saved
        }
        set {
            let value = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard value != baseURL else { return }
            UserDefaults.standard.set(value, forKey: "libereye_cloud_base_url")
            LiberEyeCloudService.shared.beginNavigationSession()
        }
    }

    static var apiToken: String {
        get { AppSecretStore.read("libereye_cloud_api_token") ?? "" }
        set {
            let value = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            guard value != apiToken else { return }
            if AppSecretStore.write(value, for: "libereye_cloud_api_token") {
                LiberEyeCloudService.shared.beginNavigationSession()
            }
        }
    }

    static var isConfigured: Bool { configurationError == nil }

    static var configurationError: LiberEyeCloudError? {
        do {
            _ = try connection()
            return nil
        } catch let error as LiberEyeCloudError {
            return error
        } catch {
            return .invalidURL
        }
    }

    static func connection() throws -> LiberEyeCloudConnection {
        try LiberEyeCloudConnection(baseURL: baseURL, apiToken: apiToken,
                                    allowsInsecureHTTP: allowsInsecureHTTP)
    }

    /// Validate and persist the address, token and mode as one configuration change.
    static func save(baseURL: String, apiToken: String, enabled: Bool) throws {
        let connection = try LiberEyeCloudConnection(baseURL: baseURL, apiToken: apiToken,
                                                     allowsInsecureHTTP: allowsInsecureHTTP)
        guard AppSecretStore.write(connection.apiToken, for: "libereye_cloud_api_token") else {
            throw LiberEyeCloudError.credentialStorageFailed
        }
        UserDefaults.standard.set(connection.baseURL.absoluteString, forKey: "libereye_cloud_base_url")
        UserDefaults.standard.set(enabled, forKey: "libereye_cloud_enabled")
        LiberEyeCloudService.shared.beginNavigationSession()
    }

    private static var allowsInsecureHTTP: Bool {
        #if DEBUG
        return AppRuntime.allowsInsecureCloud
        #else
        return false
        #endif
    }

    static var isEnabled: Bool {
        get {
            if UserDefaults.standard.object(forKey: "libereye_cloud_enabled") == nil {
                return true
            }
            return UserDefaults.standard.bool(forKey: "libereye_cloud_enabled")
        }
        set {
            guard newValue != isEnabled else { return }
            UserDefaults.standard.set(newValue, forKey: "libereye_cloud_enabled")
            LiberEyeCloudService.shared.beginNavigationSession()
        }
    }
}

@MainActor
final class LiberEyeCloudService: ObservableObject {
    static let shared = LiberEyeCloudService()

    @Published var lastPlan: LiberEyeCloudPlan?
    @Published var lastError: String?
    @Published var isCallingCloud = false
    @Published private(set) var readinessMode: LiberEyePerceptionMode?

    private(set) var navigationSessionID = UUID().uuidString
    private var inFlightRequest: Task<(Data, URLResponse), Error>?

    func beginNavigationSession() {
        inFlightRequest?.cancel()
        navigationSessionID = UUID().uuidString
        lastPlan = nil
        lastError = nil
        readinessMode = nil
    }

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 90
        return URLSession(configuration: config)
    }()

    func testConnection() async -> Bool {
        readinessMode = nil
        lastError = nil
        do {
            let connection = try LiberEyeCloudConfig.connection()
            var request = connection.request(path: "ready")
            request.timeoutInterval = 15
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
            guard connection == (try? LiberEyeCloudConfig.connection()) else { return false }
            guard let response = response as? HTTPURLResponse else {
                throw LiberEyeCloudError.invalidResponse
            }
            let readiness = try LiberEyeCloudReadiness.decode(data, statusCode: response.statusCode)
            readinessMode = readiness.perceptionMode
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    func analyze(image: UIImage, targetQuery: String? = nil,
                 detailRequest: Bool = false, wristConnected: Bool = false) async throws -> LiberEyeCloudPlan {
        do {
            return try await analyzeFrame(image: image, targetQuery: targetQuery,
                                          detailRequest: detailRequest, wristConnected: wristConnected)
        } catch {
            if !(error is CancellationError) { lastError = error.localizedDescription }
            throw error
        }
    }

    private func analyzeFrame(image: UIImage, targetQuery: String?, detailRequest: Bool,
                              wristConnected: Bool) async throws -> LiberEyeCloudPlan {
        let connection = try LiberEyeCloudConfig.connection()
        guard !isCallingCloud else { throw LiberEyeCloudError.busy }
        let requestSessionID = navigationSessionID
        isCallingCloud = true
        lastError = nil
        lastPlan = nil
        defer {
            isCallingCloud = false
            inFlightRequest = nil
        }

        guard let imageData = compressedJPEGData(from: image) else {
            throw LiberEyeCloudError.imageEncodingFailed
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = connection.request(path: "api/mobile/analyze-media", method: "POST",
                                         sessionID: requestSessionID)
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = multipartBody(
            imageData: imageData,
            targetQuery: targetQuery,
            detailRequest: detailRequest,
            wristConnected: wristConnected,
            boundary: boundary
        )

        let pendingRequest = request
        let requestTask = Task { try await session.data(for: pendingRequest) }
        inFlightRequest = requestTask
        let result: (Data, URLResponse)
        do {
            result = try await withTaskCancellationHandler {
                try await requestTask.value
            } onCancel: {
                requestTask.cancel()
            }
        } catch {
            if requestSessionID != navigationSessionID || Task.isCancelled { throw CancellationError() }
            throw error
        }
        let (data, response) = result
        try Task.checkCancellation()
        guard requestSessionID == navigationSessionID else { throw CancellationError() }
        guard connection == (try? LiberEyeCloudConfig.connection()) else { throw CancellationError() }
        guard let httpResponse = response as? HTTPURLResponse else {
            throw LiberEyeCloudError.invalidResponse
        }
        try LiberEyeCloudResponse.checkStatus(httpResponse.statusCode, data: data)

        do {
            let plan = try JSONDecoder().decode(LiberEyeCloudPlan.self, from: data)
            lastPlan = plan
            return plan
        } catch {
            throw LiberEyeCloudError.invalidResponse
        }
    }

    private func compressedJPEGData(from image: UIImage) -> Data? {
        guard image.size.width > 0, image.size.height > 0,
              image.size.width.isFinite, image.size.height.isFinite else { return nil }
        let maxSize: CGFloat = 1024
        let scale = min(maxSize / image.size.width, maxSize / image.size.height, 1.0)
        let newSize = CGSize(width: image.size.width * scale, height: image.size.height * scale)

        UIGraphicsBeginImageContextWithOptions(newSize, false, 1.0)
        image.draw(in: CGRect(origin: .zero, size: newSize))
        let resized = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        return resized?.jpegData(compressionQuality: 0.75)
    }

    private func multipartBody(imageData: Data, targetQuery: String?, detailRequest: Bool, wristConnected: Bool, boundary: String) -> Data {
        var body = Data()
        body.appendMultipartLine("--\(boundary)")
        body.appendMultipartLine("Content-Disposition: form-data; name=\"media\"; filename=\"frame.jpg\"")
        body.appendMultipartLine("Content-Type: image/jpeg")
        body.appendMultipartLine("")
        body.append(imageData)
        body.appendMultipartLine("")

        if let targetQuery, !targetQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body.appendMultipartLine("--\(boundary)")
            body.appendMultipartLine("Content-Disposition: form-data; name=\"target_query\"")
            body.appendMultipartLine("")
            body.appendMultipartLine(targetQuery)
        }

        for (name, value) in [("detail_request", detailRequest), ("wrist_connected", wristConnected)] {
            body.appendMultipartLine("--\(boundary)")
            body.appendMultipartLine("Content-Disposition: form-data; name=\"\(name)\"")
            body.appendMultipartLine("")
            body.appendMultipartLine(value ? "true" : "false")
        }
        body.appendMultipartLine("--\(boundary)--")
        return body
    }
}

private extension Data {
    mutating func appendMultipartLine(_ line: String) {
        append(Data("\(line)\r\n".utf8))
    }
}
