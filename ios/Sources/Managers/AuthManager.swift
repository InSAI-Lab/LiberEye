//
//  AuthManager.swift
//  LiberEye
//
//  Account state, token refresh and user information
//

import Foundation
import Combine
import SwiftUI

// MARK: - Authentication interface for injection and previews
protocol AuthManaging: ObservableObject {
    var isLoggedIn: Bool { get }
    var isLoggingIn: Bool { get }
    var showLoginSheet: Bool { get set }
    var errorMessage: String? { get }
    func presentLogin()
}

// MARK: - Sign-in method
enum LoginMethod: String {
    case anonymous = "Guest sign-in"
    case phone = "Phone sign-in"
    case none = "Signed out"
}

// MARK: - AuthManager
class AuthManager: AuthManaging {

    // MARK: - Singleton
    static let shared = AuthManager()

    // MARK: - Published state
    @Published private(set) var isLoggedIn: Bool = false
    @Published private(set) var isLoggingIn: Bool = false
    @Published private(set) var loginMethod: LoginMethod = .none
    @Published private(set) var currentUser: CloudBaseUser?
    @Published private(set) var errorMessage: String?
    @Published var showLoginSheet: Bool = false

    // MARK: - Private state
    private let cloudBaseService = CloudBaseService.shared
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Initialization
    private init() {
        // Defer the state check to avoid publishing changes during initialization.
        DispatchQueue.main.async { [weak self] in
            self?.checkLoginStatus()
        }
    }

    // MARK: - Authentication status
    func checkLoginStatus() {
        if UserDefaults.standard.bool(forKey: "local_guest_login") {
            isLoggedIn = true
            loginMethod = .anonymous
        } else if let _ = cloudBaseService.getAccessToken() {
            isLoggedIn = true
            loginMethod = .anonymous
        } else {
            isLoggedIn = false
            loginMethod = .none
        }
    }

    // MARK: - Guest sign-in
    func loginAnonymously() async {
        guard !isLoggingIn else { return }

        isLoggingIn = true
        errorMessage = nil

        do {
            let _ = try await cloudBaseService.anonymousLogin()
            UserDefaults.standard.set(false, forKey: "local_guest_login")
            isLoggedIn = true
            loginMethod = .anonymous
        } catch {
            startLocalGuestSession()
        }

        isLoggingIn = false
    }

    // MARK: - Phone sign-in flow

    /// Step 1: request a verification code.
    func sendVerificationCode(phoneNumber: String) async throws -> String {
        // Normalize the phone number.
        let formatted = formatPhoneNumber(phoneNumber)
        let response = try await cloudBaseService.sendVerificationCode(phoneNumber: formatted)

        guard let vId = response.verificationId, !vId.isEmpty else {
            throw NSError(domain: "AuthManager", code: 400, userInfo: [
                NSLocalizedDescriptionKey: "Could not send a verification code. Try again."
            ])
        }
        return vId
    }

    /// Step 2: verify the code and sign in.
    func verifyAndLogin(verificationId: String, code: String, phoneNumber: String) async throws {
        guard !isLoggingIn else { return }

        isLoggingIn = true
        defer { isLoggingIn = false }
        errorMessage = nil

        do {
            // Verify the submitted code.
            let verifyResponse = try await cloudBaseService.verifyCode(
                verificationId: verificationId,
                code: code
            )

            // Validate the verification response.
            guard let token = verifyResponse.verificationToken, !token.isEmpty else {
                throw NSError(domain: "AuthManager", code: 400, userInfo: [
                    NSLocalizedDescriptionKey: "Could not verify the code. Try again."
                ])
            }

            // Sign in or register.
            let formattedPhone = formatPhoneNumber(phoneNumber)
            let loginResponse = try await cloudBaseService.phoneLogin(
                phoneNumber: formattedPhone,
                verificationCode: code,
                verificationToken: token
            )

            // Store user information.
            if let uid = loginResponse.uid {
                UserDefaults.standard.set(uid, forKey: "cb_uid")
            }
            if let loginType = loginResponse.loginType {
                UserDefaults.standard.set(loginType, forKey: "cb_login_type")
            }

            isLoggedIn = true
            loginMethod = .phone
            showLoginSheet = false

        } catch {
            errorMessage = error.localizedDescription
            throw error
        }

        isLoggingIn = false
    }

    /// Refresh the token.
    func refreshTokenIfNeeded() async {
        guard isLoggedIn, let expiresAt = UserDefaults.standard.object(forKey: "cb_token_expires_at") as? Date else {
            return
        }

        // Refresh tokens that expire within five minutes.
        if expiresAt.timeIntervalSinceNow < 300 {
            do {
                _ = try await cloudBaseService.refreshAccessToken()
            } catch {
                // Try guest sign-in when token refresh fails.
                await loginAnonymously()
            }
        }
    }

    /// Fetch user information.
    func fetchUserInfo() async {
        guard isLoggedIn else { return }

        do {
            currentUser = try await cloudBaseService.getCurrentUser()
        } catch {
            // Keep the current state if the request fails.
        }
    }

    /// Sign out.
    func logout() async {
        await cloudBaseService.logout()
        UserDefaults.standard.set(false, forKey: "local_guest_login")
        isLoggedIn = false
        loginMethod = .none
        currentUser = nil
    }

    /// Present the sign-in sheet.
    func presentLogin() {
        showLoginSheet = true
    }

    /// Dismiss the sign-in sheet.
    func dismissLogin() {
        showLoginSheet = false
        errorMessage = nil
    }

    // MARK: - Private helpers

    /// Format a phone number for the authentication API.
    private func formatPhoneNumber(_ phone: String) -> String {
        let cleaned = phone.replacingOccurrences(of: " ", with: "")
        if cleaned.hasPrefix("+86") {
            // Add the separator to an international number.
            let number = String(cleaned.dropFirst(3))
            return "+86 \(number)"
        } else if cleaned.hasPrefix("86") {
            let number = String(cleaned.dropFirst(2))
            return "+86 \(number)"
        } else {
            return "+86 \(cleaned)"
        }
    }

    private func startLocalGuestSession() {
        let localId = UserDefaults.standard.string(forKey: "local_guest_uid") ?? "guest-\(UUID().uuidString)"
        UserDefaults.standard.set(localId, forKey: "local_guest_uid")
        UserDefaults.standard.set(localId, forKey: "cb_uid")
        UserDefaults.standard.set("local_guest", forKey: "cb_login_type")
        UserDefaults.standard.set(true, forKey: "local_guest_login")
        isLoggedIn = true
        loginMethod = .anonymous
        errorMessage = nil
    }

    // MARK: - Stored account identifiers

    var userId: String? {
        UserDefaults.standard.string(forKey: "cb_uid")
    }

    var isPhoneLogin: Bool {
        loginMethod == .phone
    }

    var isAnonymous: Bool {
        loginMethod == .anonymous
    }
}
