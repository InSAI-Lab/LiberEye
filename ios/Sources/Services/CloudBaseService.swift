//
//  CloudBaseService.swift
//  LiberEye
//
//  Native iOS client for the CloudBase HTTP API.
//

import Foundation
import Combine
import UIKit

// MARK: - CloudBase service errors
enum CloudBaseServiceError: Error, LocalizedError {
    case notConfigured          // Environment not configured
    case networkError(String)   // Network error
    case serverError(Int, String)  // HTTP error
    case decodingError(Error)  // JSON decoding failed
    case authError(String)      // Authentication error
    case apiError(String)       // API operation error
    case unknown

    var errorDescription: String? {
        switch self {
        case .notConfigured:
            return "CloudBase is not configured. Select an environment in Settings"
        case .networkError(let msg):
            return "Network error: \(msg)"
        case .serverError(let code, let msg):
            return "Server error (\(code)): \(msg)"
        case .decodingError(let err):
            return "Failed to decode data: \(err.localizedDescription)"
        case .authError(let msg):
            return "Authentication failed: \(msg)"
        case .apiError(let msg):
            return "API error: \(msg)"
        case .unknown:
            return "Unknown error"
        }
    }
}

// MARK: - CloudBaseService
class CloudBaseService: ObservableObject {

    // MARK: - Singleton
    static let shared = CloudBaseService()

    // MARK: - Published state
    @Published private(set) var isConfigured: Bool = false
    @Published private(set) var isConnected: Bool = false
    @Published private(set) var connectionError: String?

    // MARK: - Private properties
    private var config: CloudBaseConfig = .placeholder
    private var accessToken: String?
    private var refreshToken: String?
    private var tokenExpiresAt: Date?

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        return URLSession(configuration: config)
    }()

    // MARK: - Device identifier for anonymous sessions
    private var deviceId: String {
        if let existing = UserDefaults.standard.string(forKey: "cb_device_id") {
            return existing
        }
        let newId = UUID().uuidString
        UserDefaults.standard.set(newId, forKey: "cb_device_id")
        return newId
    }

    private var requestId: String {
        UUID().uuidString
    }

    private let jsonDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: dateString) {
                return date
            }
            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
                return date
            }
            // Try a Unix timestamp.
            if let timestamp = Double(dateString) {
                return Date(timeIntervalSince1970: timestamp)
            }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unable to parse date: \(dateString)")
        }
        return decoder
    }()

    // MARK: - Initialization
    private init() {
        // Load configuration asynchronously to avoid changing published properties during initialization.
        DispatchQueue.main.async { [weak self] in
            self?.loadConfig()
        }
    }

    // MARK: - Configuration management
    func configure(envId: String, region: String = "ap-shanghai") {
        self.config = CloudBaseConfig(envId: envId, region: region, baseURL: "")
        self.isConfigured = !envId.isEmpty
        self.connectionError = nil
        saveConfig()
    }

    func clearConfig() {
        self.config = .placeholder
        self.isConfigured = false
        self.isConnected = false
        clearTokens()
    }

    func clearTokens() {
        self.accessToken = nil
        self.refreshToken = nil
        self.tokenExpiresAt = nil
        AppSecretStore.write("", for: "cb_access_token")
        AppSecretStore.write("", for: "cb_refresh_token")
        UserDefaults.standard.removeObject(forKey: "cb_token_expires_at")
    }

    // MARK: - Token management
    func setTokens(access: String, refresh: String, expiresIn: Int) {
        self.accessToken = access
        self.refreshToken = refresh
        self.tokenExpiresAt = Date().addingTimeInterval(TimeInterval(expiresIn))
        AppSecretStore.write(access, for: "cb_access_token")
        AppSecretStore.write(refresh, for: "cb_refresh_token")
        UserDefaults.standard.set(tokenExpiresAt, forKey: "cb_token_expires_at")
    }

    func getAccessToken() -> String? {
        if let token = accessToken { return token }
        return AppSecretStore.read("cb_access_token")
    }

    // MARK: - Connection check
    func testConnection() async -> Bool {
        guard isConfigured else {
            connectionError = "Environment not configured"
            return false
        }
        // Check connectivity with anonymous sign-in.
        do {
            let _ = try await anonymousLogin()
            isConnected = true
            connectionError = nil
            return true
        } catch {
            isConnected = false
            connectionError = error.localizedDescription
            return false
        }
    }

    // MARK: - Authentication

    /// Sign in as a guest without registration.
    func anonymousLogin() async throws -> CloudBaseLoginResponse {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.authBaseURL)/signin-anonymously")!

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(deviceId, forHTTPHeaderField: "x-device-id")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = "{}".data(using: .utf8)

        // Anonymous sign-in uses the publishable key as its bearer token.
        let publishableKey = getPublishableKey()
        if !publishableKey.isEmpty {
            request.setValue("Bearer \(publishableKey)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await session.data(for: request)

        // Check the HTTP status.
        if let httpResponse = response as? HTTPURLResponse {
            print("HTTP Status Code: \(httpResponse.statusCode)")
        }

        try validateResponse(response)

        do {
            let loginResponse = try jsonDecoder.decode(CloudBaseLoginResponse.self, from: data)

            // Validate required fields.
            guard let accessToken = loginResponse.accessToken,
                  let refreshToken = loginResponse.refreshToken,
                  let expiresIn = loginResponse.expiresIn else {
                print("Missing required fields in login response")
                throw CloudBaseServiceError.decodingError(NSError(domain: "", code: 0, userInfo: [
                    NSLocalizedDescriptionKey: "The login response is missing required fields"
                ]))
            }

            setTokens(access: accessToken, refresh: refreshToken, expiresIn: expiresIn)
            isConnected = true
            return loginResponse
        } catch {
            print("JSON Decode Error: \(error)")
            throw CloudBaseServiceError.decodingError(error)
        }
    }

    /// Request a phone verification code.
    func sendVerificationCode(phoneNumber: String) async throws -> CloudBaseVerificationResponse {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.authBaseURL)/verification")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(deviceId, forHTTPHeaderField: "x-device-id")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        // Use international phone format with a space, for example "+86 13800138000".
        let body = ["phone_number": phoneNumber]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)


        do {
            return try jsonDecoder.decode(CloudBaseVerificationResponse.self, from: data)
        } catch {
            throw CloudBaseServiceError.decodingError(error)
        }
    }

    /// Validate the verification code.
    func verifyCode(verificationId: String, code: String) async throws -> CloudBaseVerifyResponse {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.authBaseURL)/verification/verify")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(deviceId, forHTTPHeaderField: "x-device-id")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "verification_id": verificationId,
            "verification_code": code
        ]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)


        do {
            return try jsonDecoder.decode(CloudBaseVerifyResponse.self, from: data)
        } catch {
            throw CloudBaseServiceError.decodingError(error)
        }
    }

    /// Register and sign in with a phone number.
    func phoneLogin(phoneNumber: String, verificationCode: String, verificationToken: String) async throws -> CloudBaseLoginResponse {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.authBaseURL)/signup")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(deviceId, forHTTPHeaderField: "x-device-id")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "phone_number": phoneNumber,
            "verification_code": verificationCode,
            "verification_token": verificationToken,
            "name": "Phone user"
        ]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)


        do {
            let loginResponse = try jsonDecoder.decode(CloudBaseLoginResponse.self, from: data)

            // Validate required fields.
            guard let accessToken = loginResponse.accessToken,
                  let refreshToken = loginResponse.refreshToken,
                  let expiresIn = loginResponse.expiresIn else {
                print("Missing required fields in phone login response")
                throw CloudBaseServiceError.decodingError(NSError(domain: "", code: 0, userInfo: [
                    NSLocalizedDescriptionKey: "The login response is missing required fields"
                ]))
            }

            setTokens(access: accessToken, refresh: refreshToken, expiresIn: expiresIn)
            isConnected = true
            return loginResponse
        } catch {
            throw CloudBaseServiceError.decodingError(error)
        }
    }

    /// Refresh the access token.
    func refreshAccessToken() async throws -> CloudBaseTokenRefreshResponse {
        guard let refresh = refreshToken ?? AppSecretStore.read("cb_refresh_token") else {
            throw CloudBaseServiceError.authError("No refresh token is available")
        }

        let url = URL(string: "\(config.authBaseURL)/token")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(deviceId, forHTTPHeaderField: "x-device-id")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "grant_type": "refresh_token",
            "refresh_token": refresh
        ]
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        let tokenResponse = try jsonDecoder.decode(CloudBaseTokenRefreshResponse.self, from: data)
        setTokens(access: tokenResponse.accessToken, refresh: tokenResponse.refreshToken, expiresIn: tokenResponse.expiresIn)
        return tokenResponse
    }

    /// Get the current user.
    func getCurrentUser() async throws -> CloudBaseUser {
        guard let token = getAccessToken() else {
            throw CloudBaseServiceError.authError("Not signed in")
        }

        let url = URL(string: "\(config.authBaseURL)/user/me")!
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.setValue(requestId, forHTTPHeaderField: "x-request-id")

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)
        return try jsonDecoder.decode(CloudBaseUser.self, from: data)
    }

    /// Sign out
    func logout() async {
        if let token = getAccessToken() {
            let url = URL(string: "\(config.authBaseURL)/revoke")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"
            request.setValue(requestId, forHTTPHeaderField: "x-request-id")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body = ["token": token]
            request.httpBody = try? JSONEncoder().encode(body)
            _ = try? await session.data(for: request)
        }
        clearTokens()
        isConnected = false
    }

    // MARK: - Cloud functions

    /// Invoke a cloud function through its HTTP trigger.
    func callFunction<T: Codable>(name: String, data: [String: Any] = [:]) async throws -> T {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.apiBaseURL)/v1/functions/\(name)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: data)

        let (responseData, response) = try await session.data(for: request)
        try validateResponse(response)

        return try JSONDecoder().decode(T.self, from: responseData)
    }

    /// Invoke a cloud function and return its JSON response.
    func callFunctionRaw(name: String, data: [String: Any] = [:]) async throws -> [String: Any] {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.apiBaseURL)/v1/functions/\(name)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: data)

        let (responseData, response) = try await session.data(for: request)
        try validateResponse(response)

        guard let json = try JSONSerialization.jsonObject(with: responseData) as? [String: Any] else {
            throw CloudBaseServiceError.decodingError(NSError(domain: "", code: 0, userInfo: [NSLocalizedDescriptionKey: "The response is not valid JSON"]))
        }
        return json
    }

    // MARK: - MySQL database operations

    /// Query records.
    func query<T: Codable>(
        table: String,
        select: String = "*",
        filters: [String: String] = [:],
        order: String? = nil,
        limit: Int = 20,
        offset: Int = 0
    ) async throws -> [T] {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        var queryItems = [URLQueryItem(name: "select", value: select)]
        queryItems.append(URLQueryItem(name: "limit", value: "\(limit)"))
        queryItems.append(URLQueryItem(name: "offset", value: "\(offset)"))

        for (key, value) in filters {
            queryItems.append(URLQueryItem(name: key, value: value))
        }

        if let order = order {
            queryItems.append(URLQueryItem(name: "order", value: order))
        }

        var components = URLComponents(string: "\(config.apiBaseURL)/v1/rdb/rest/\(table)")!
        components.queryItems = queryItems

        guard let url = components.url else {
            throw CloudBaseServiceError.networkError("Failed to construct the URL")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await session.data(for: request)
        try validateResponse(response)

        return try jsonDecoder.decode([T].self, from: data)
    }

    /// Insert a record.
    func insert<T: Codable>(table: String, data: [String: Any]) async throws -> T {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.apiBaseURL)/v1/rdb/rest/\(table)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("return=representation", forHTTPHeaderField: "Prefer")

        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: data)

        let (responseData, response) = try await session.data(for: request)
        try validateResponse(response)

        return try jsonDecoder.decode(T.self, from: responseData)
    }

    /// Update a record.
    func update<T: Codable>(table: String, filter: String, data: [String: Any]) async throws -> [T] {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.apiBaseURL)/v1/rdb/rest/\(table)?\(filter)")!
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("return=representation", forHTTPHeaderField: "Prefer")

        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: data)

        let (responseData, response) = try await session.data(for: request)
        try validateResponse(response)

        return try jsonDecoder.decode([T].self, from: responseData)
    }

    /// Delete a record.
    func delete(table: String, filter: String) async throws {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let url = URL(string: "\(config.apiBaseURL)/v1/rdb/rest/\(table)?\(filter)")!
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"

        if let token = getAccessToken() {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (_, response) = try await session.data(for: request)
        try validateResponse(response)
    }

    // MARK: - Upload path provisioning

    private func getUploadCredentials() async throws -> [String: Any] {
        guard isConfigured else { throw CloudBaseServiceError.notConfigured }

        let result: [String: Any] = try await callFunctionRaw(name: "getUploadCredentials")
        return result
    }

    /// Request a destination path from the deployment-provided `getUploadCredentials` cloud function.
    /// This operation does not transfer file data or confirm that a file exists.
    func requestUploadPath() async throws -> String {
        let credentials = try await getUploadCredentials()
        guard let path = credentials["filePath"] as? String else {
            throw CloudBaseServiceError.apiError("Invalid upload credentials")
        }
        return path
    }

    // MARK: - Private methods

    private func validateResponse(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CloudBaseServiceError.unknown
        }

        switch httpResponse.statusCode {
        case 200...299:
            return
        case 401:
            throw CloudBaseServiceError.authError("Authentication failed. Sign in again")
        case 403:
            throw CloudBaseServiceError.authError("Access denied")
        case 404:
            throw CloudBaseServiceError.apiError("Resource not found")
        default:
            throw CloudBaseServiceError.serverError(httpResponse.statusCode, "HTTP \(httpResponse.statusCode)")
        }
    }

    private func getPublishableKey() -> String {
        // Read the publishable key from configuration or UserDefaults.
        return UserDefaults.standard.string(forKey: "cb_publishable_key") ?? CloudBaseDefaults.publishableKey
    }

    private func saveConfig() {
        if isConfigured {
            UserDefaults.standard.set(config.envId, forKey: "cb_env_id")
            UserDefaults.standard.set(config.region, forKey: "cb_region")
        }
    }

    private func loadConfig() {
        let envId = UserDefaults.standard.string(forKey: "cb_env_id") ?? CloudBaseDefaults.envId
        let region = UserDefaults.standard.string(forKey: "cb_region") ?? CloudBaseDefaults.region
        configure(envId: envId, region: region)

        // Restore the saved token.
        if let token = AppSecretStore.read("cb_access_token") {
            self.accessToken = token
        }
        if let refresh = AppSecretStore.read("cb_refresh_token") {
            self.refreshToken = refresh
        }
        if let expiresAt = UserDefaults.standard.object(forKey: "cb_token_expires_at") as? Date {
            self.tokenExpiresAt = expiresAt
        }

        // Check token expiration.
        if let expiresAt = tokenExpiresAt, expiresAt > Date() {
            self.isConnected = true
        }
    }
}
