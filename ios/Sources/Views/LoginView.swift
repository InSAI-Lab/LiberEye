//
//  LoginView.swift
//  LiberEye
//
//  Accessible sign-in view.
//

import SwiftUI
import Combine
import AVFoundation

struct LoginView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var authManager: AuthManager
    @ObservedObject private var cloudBaseService = CloudBaseService.shared

    @State private var phoneNumber: String = ""
    @State private var verificationCode: String = ""
    @State private var verificationId: String = ""
    @State private var countdown: Int = 0
    @State private var isSendingCode: Bool = false
    @State private var isVerifying: Bool = false
    @State private var localError: String?
    @State private var showCodeField: Bool = false

    let countdownTimer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 0) {
            headerView

            ScrollView {
                VStack(spacing: 24) {
                    if cloudBaseService.isConfigured {
                        phoneInputView
                    } else {
                        cloudBaseUnavailableView
                    }

                    if showCodeField {
                        codeInputView
                    }

                    if let error = localError ?? authManager.errorMessage {
                        errorView(error)
                    }

                    actionButtonsView
                }
                .padding(24)
            }

            Spacer()

            guestLoginButton
        }
        .background(Color(.systemBackground))
        .onReceive(countdownTimer) { _ in
            if countdown > 0 {
                countdown -= 1
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("LiberEye sign-in page")
    }

    // MARK: - Header
    private var headerView: some View {
        VStack(spacing: 8) {
            Text("Sign in")
                .font(.largeTitle.bold())
                .accessibilityAddTraits(.isHeader)

            Text("Sign in to sync data to the cloud.")
                .font(.body)
                .foregroundColor(.secondary)
        }
        .padding(.top, 20)
        .padding(.bottom, 16)
    }

    // MARK: - Phone number input
    private var phoneInputView: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Phone number")
                .font(.headline)

            HStack(spacing: 12) {
                Text("+86")
                    .font(.title2)
                    .frame(width: 50)

                TextField("Enter your phone number", text: $phoneNumber)
                    .keyboardType(.phonePad)
                    .font(.title2)
                    .padding(12)
                    .background(Color(.secondarySystemBackground))
                    .cornerRadius(8)
            }

            Button(action: sendVerificationCode) {
                HStack {
                    if isSendingCode {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else if countdown > 0 {
                        Text("Code sent. Resend in \(countdown) seconds.")
                    } else {
                        Image(systemName: "message.fill")
                        Text("Send verification code")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(countdown > 0 ? Color.gray : Color.blue)
                .foregroundColor(.white)
                .font(.headline)
                .cornerRadius(12)
            }
            .disabled(phoneNumber.count < 11 || isSendingCode || countdown > 0)
            .accessibilityLabel("Send a verification code to \(phoneNumber)")
        }
    }

    private var cloudBaseUnavailableView: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: "icloud.slash.fill")
                    .foregroundColor(.orange)
                Text("CloudBase is not configured")
                    .font(.headline)
            }

            Text("Phone sign-in requires a CloudBase environment configured in Settings. You can continue as a guest with data stored on this device.")
                .font(.body)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .background(Color.orange.opacity(0.12))
        .cornerRadius(12)
        .accessibilityLabel("CloudBase is not configured. Continue as a guest.")
    }

    // MARK: - Verification code input
    private var codeInputView: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Verification code")
                .font(.headline)

            HStack(spacing: 12) {
                TextField("Enter your verification code", text: $verificationCode)
                    .keyboardType(.numberPad)
                    .font(.title)
                    .multilineTextAlignment(.center)
                    .padding(16)
                    .background(Color(.secondarySystemBackground))
                    .cornerRadius(8)
                    .accessibilityLabel("Verification code field, \(verificationCode.count) digits entered.")

                Text("\(verificationCode.count)/6")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .transition(.opacity.combined(with: .move(edge: .top)))
    }

    // MARK: - Error message
    private func errorView(_ message: String) -> some View {
        HStack {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(.red)
            Text(message)
                .font(.body)
                .foregroundColor(.red)
        }
        .padding()
        .background(Color.red.opacity(0.1))
        .cornerRadius(8)
        .accessibilityLabel("Error: \(message)")
    }

    // MARK: - Action buttons
    private var actionButtonsView: some View {
        VStack(spacing: 16) {
            Button(action: verifyAndLogin) {
                HStack {
                    if isVerifying {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Image(systemName: "checkmark.circle.fill")
                        Text("Sign in")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 18)
                .background(cloudBaseService.isConfigured && verificationCode.count == 6 ? Color.blue : Color.gray)
                .foregroundColor(.white)
                .font(.headline)
                .cornerRadius(12)
            }
            .disabled(!cloudBaseService.isConfigured || verificationCode.count != 6 || isVerifying)
            .accessibilityLabel("Sign in")

            Text("An account is created automatically for a new phone number.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }

    // MARK: - Guest sign-in button
    private var guestLoginButton: some View {
        Button(action: anonymousLogin) {
            VStack(spacing: 4) {
                Image(systemName: "person.crop.circle")
                    .font(.title2)
                Text("Continue as a guest")
                    .font(.body)
            }
            .foregroundColor(.secondary)
            .padding(.vertical, 20)
        }
        .accessibilityLabel("Continue as a guest")
        .padding(.bottom, 20)
    }

    // MARK: - Send verification code
    private func sendVerificationCode() {
        isSendingCode = true
        localError = nil

        Task {
            do {
                let vId = try await authManager.sendVerificationCode(phoneNumber: phoneNumber)
                verificationId = vId
                UserDefaults.standard.set(phoneNumber, forKey: "pending_phone")

                await MainActor.run {
                    withAnimation {
                        showCodeField = true
                    }
                    countdown = 60
                    speakText("Verification code sent. Check your text messages.")
                }
            } catch {
                await MainActor.run {
                    localError = error.localizedDescription
                    speakText("Unable to send verification code: \(error.localizedDescription)")
                }
            }

            await MainActor.run {
                isSendingCode = false
            }
        }
    }

    // MARK: - Verify and sign in
    private func verifyAndLogin() {
        isVerifying = true
        localError = nil

        Task {
            do {
                try await authManager.verifyAndLogin(
                    verificationId: verificationId,
                    code: verificationCode,
                    phoneNumber: phoneNumber
                )
                await MainActor.run {
                    speakText("Signed in. Welcome to LiberEye.")
                    dismiss()
                }
            } catch {
                await MainActor.run {
                    localError = error.localizedDescription
                    speakText("Sign-in failed: \(error.localizedDescription)")
                }
            }

            await MainActor.run {
                isVerifying = false
            }
        }
    }

    // MARK: - Guest sign-in
    private func anonymousLogin() {
        Task {
            await authManager.loginAnonymously()
            await MainActor.run {
                if authManager.isLoggedIn {
                    speakText("Continuing as a guest.")
                    dismiss()
                } else if let error = authManager.errorMessage {
                    localError = error
                    speakText("Guest sign-in failed: \(error)")
                }
            }
        }
    }

    // MARK: - Speech helper
    private func speakText(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        let savedRate = UserDefaults.standard.object(forKey: "speech_rate") as? Double ?? 0.72
        utterance.rate = min(max(Float(savedRate), AVSpeechUtteranceMinimumSpeechRate), AVSpeechUtteranceMaximumSpeechRate)
        let synthesizer = AVSpeechSynthesizer()
        synthesizer.speak(utterance)
    }
}

#Preview {
    LoginView()
        .environmentObject(AuthManager.shared)
}
