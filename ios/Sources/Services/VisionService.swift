//
//  VisionService.swift
//  LiberEye
//
//  Scene analysis through Doubao, including OCR, scene descriptions and store recognition.
//

import Foundation
import UIKit
import Vision
import Combine
import SwiftUI

// MARK: - Image analysis modes
enum SceneAnalysisMode: String, CaseIterable {
    case scene = "Scene description"    // Describe the overall scene.
    case text = "Text recognition"      // Read visible text.
    case store = "Store recognition"    // Identify stores and buildings.
    case obstacle = "Obstacle analysis" // Assess obstacles and passage safety.
    case fullAnalysis = "Full analysis" // Combine all scene information.

    var systemPrompt: String {
        switch self {
        case .scene:
            return """
            Assist a person with a visual impairment by briefly describing this scene in English.
            Include whether it is indoors or outdoors, major object locations, people and visible passages.
            Use clear, natural speech in fewer than 100 words. State uncertainty when appropriate.
            """
        case .text:
            return """
            Assist a person with a visual impairment by reading all visible text from top to bottom and left to right.
            Briefly explain the structure of menus, price lists or similar content.
            Respond in English using natural speech. Translate non-English text and identify unclear text.
            """
        case .store:
            return """
            Assist a person with a visual impairment by identifying visible stores, buildings and facilities.
            Describe their type, such as a restaurant, supermarket, bank or hospital, and the apparent entrance location.
            Respond in English in fewer than 80 words. Do not invent unreadable names or hidden entrances.
            """
        case .obstacle:
            return """
            Assist a person with a visual impairment by describing visible obstacles and passage conditions.
            Mention approximate proximity (near, medium or far), steps, holes and thresholds when visible.
            Provide concise guidance in English in fewer than 80 words without claiming that an unseen path is safe.
            """
        case .fullAnalysis:
            return """
            Assist a person with a visual impairment by analyzing the image in four short sections:
            1. Scene: the environment and overall conditions.
            2. Text: important visible text, including store names, signs and notices.
            3. Obstacles: visible obstacles and passage conditions.
            4. Guidance: one sentence suggesting a cautious next action.
            Respond in English with fewer than 30 words per section, using natural speech and stating uncertainty.
            """
        }
    }

    var userPrompt: String {
        switch self {
        case .scene: return "Describe the scene in this image."
        case .text: return "Read all visible text in this image."
        case .store: return "Identify the stores or buildings in this image."
        case .obstacle: return "Describe visible obstacles and passage conditions in this image."
        case .fullAnalysis: return "Analyze the image across all four sections."
        }
    }

    var displayName: String {
        let language = AppLanguageManager.shared
        switch self {
        case .scene: return language.text("scene_description")
        case .text: return language.text("text_recognition")
        case .store: return language.text("store_recognition")
        case .obstacle: return language.text("obstacle_analysis")
        case .fullAnalysis: return language.text("full_analysis")
        }
    }

    var icon: String {
        switch self {
        case .scene: return "eye.fill"
        case .text: return "doc.text.fill"
        case .store: return "storefront.fill"
        case .obstacle: return "exclamationmark.triangle.fill"
        case .fullAnalysis: return "sparkles"
        }
    }
}

// MARK: - Doubao API configuration
struct DoubaoConfig {
    // Optional direct model access is configured by the user, never embedded in source.
    static var apiKey: String {
        get { AppSecretStore.read("doubao_api_key") ?? "" }
        set { AppSecretStore.write(newValue, for: "doubao_api_key") }
    }
    static var modelId: String = UserDefaults.standard.string(forKey: "doubao_model_id") ?? "doubao-seed-1-6-flash-250828"
    static let baseURL = "https://ark.cn-beijing.volces.com/api/v3/responses"

    static func save(apiKey: String, modelId: String) {
        AppSecretStore.write(apiKey, for: "doubao_api_key")
        UserDefaults.standard.set(modelId, forKey: "doubao_model_id")
        Self.apiKey = apiKey
        Self.modelId = modelId
    }

    static var isConfigured: Bool {
        return !apiKey.isEmpty
    }
}

// MARK: - Image analysis response
struct SceneAnalysisResult {
    let mode: SceneAnalysisMode
    let content: String
    let timestamp: Date
    let processingTime: TimeInterval

    var voiceText: String {
        // Remove Markdown formatting for natural speech.
        return content
            .replacingOccurrences(of: "**", with: "")
            .replacingOccurrences(of: "##", with: "")
            .replacingOccurrences(of: "[", with: "")
            .replacingOccurrences(of: "]", with: ", ")
    }
}

// MARK: - Scene analysis service
@MainActor
class VisionService: ObservableObject {

    @Published var isAnalyzing: Bool = false
    @Published var lastResult: SceneAnalysisResult? = nil
    @Published var error: String? = nil
    @Published var selectedMode: SceneAnalysisMode = .fullAnalysis
    @Published var lastConversationAnswer: String? = nil

    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = 120
        return URLSession(configuration: config)
    }()

    // MARK: - Image analysis entry point
    func analyze(image: UIImage, mode: SceneAnalysisMode? = nil) async {
        let analysisMode = mode ?? selectedMode
        isAnalyzing = true
        error = nil

        let startTime = Date()

        do {
            // Compress the image
            guard let imageData = compressImage(image) else {
                throw VisionError.imageProcessingFailed
            }
            let base64Image = imageData.base64EncodedString()

            // Call the Doubao API
            let content = try await callDoubaoAPI(
                base64Image: base64Image,
                mode: analysisMode
            )

            let processingTime = Date().timeIntervalSince(startTime)
            lastResult = SceneAnalysisResult(
                mode: analysisMode,
                content: content,
                timestamp: Date(),
                processingTime: processingTime
            )

        } catch {
            self.error = formatError(error)
        }

        isAnalyzing = false
    }

    // MARK: - Local OCR without a network connection
    func quickOCR(image: UIImage) async -> String {
        return await withCheckedContinuation { continuation in
            guard let cgImage = image.cgImage else {
                continuation.resume(returning: "Image processing failed")
                return
            }

            let request = VNRecognizeTextRequest { request, error in
                guard let observations = request.results as? [VNRecognizedTextObservation],
                      !observations.isEmpty else {
                    continuation.resume(returning: "No text recognized")
                    return
                }

                let recognizedText = observations
                    .compactMap { $0.topCandidates(1).first?.string }
                    .joined(separator: "\n")

                continuation.resume(returning: recognizedText.isEmpty ? "No text recognized" : recognizedText)
            }

            request.recognitionLanguages = ["en-US", "zh-Hans", "zh-Hant"]
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true

            let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
            try? handler.perform([request])
        }
    }

    // MARK: - Text conversation
    func ask(_ question: String, context: String? = nil) async -> String? {
        let trimmedQuestion = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedQuestion.isEmpty else { return nil }

        isAnalyzing = true
        error = nil
        defer { isAnalyzing = false }

        do {
            let answer = try await callDoubaoTextAPI(question: trimmedQuestion, context: context)
            lastConversationAnswer = answer
            return answer
        } catch {
            self.error = formatError(error)
            return nil
        }
    }

    // MARK: - Private Doubao API request
    private func callDoubaoAPI(base64Image: String, mode: SceneAnalysisMode) async throws -> String {
        guard DoubaoConfig.isConfigured else {
            throw VisionError.notConfigured
        }

        guard let url = URL(string: DoubaoConfig.baseURL) else {
            throw VisionError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(DoubaoConfig.apiKey)", forHTTPHeaderField: "Authorization")

        let maxOutputTokens: Int
        switch mode {
        case .scene, .obstacle, .store:
            maxOutputTokens = 180
        case .text, .fullAnalysis:
            maxOutputTokens = 360
        }

        let body: [String: Any] = [
            "model": DoubaoConfig.modelId,
            "input": [
                [
                    "role": "system",
                    "content": [
                        [
                            "type": "input_text",
                            "text": mode.systemPrompt
                        ]
                    ]
                ],
                [
                    "role": "user",
                    "content": [
                        [
                            "type": "input_image",
                            "image_url": "data:image/jpeg;base64,\(base64Image)"
                        ],
                        [
                            "type": "input_text",
                            "text": mode.userPrompt
                        ]
                    ]
                ]
            ],
            "max_output_tokens": maxOutputTokens,
            "temperature": 0.2
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw VisionError.networkError("Invalid response")
        }

        guard httpResponse.statusCode == 200 else {
            if httpResponse.statusCode == 401 {
                throw VisionError.authenticationFailed
            }
            let message = String(data: data, encoding: .utf8) ?? "No error details"
            throw VisionError.serverError(httpResponse.statusCode, message)
        }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            let raw = String(data: data, encoding: .utf8) ?? "Non-text response"
            throw VisionError.parsingFailed(raw)
        }

        guard let content = parseResponsesOutput(json) else {
            let raw = String(data: data, encoding: .utf8) ?? "\(json)"
            throw VisionError.parsingFailed(raw)
        }

        return content
    }

    private func callDoubaoTextAPI(question: String, context: String?) async throws -> String {
        guard DoubaoConfig.isConfigured else {
            throw VisionError.notConfigured
        }

        guard let url = URL(string: DoubaoConfig.baseURL) else {
            throw VisionError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(DoubaoConfig.apiKey)", forHTTPHeaderField: "Authorization")

        var prompt = """
        You are the voice assistant in the LiberEye app. Respond in clear, concise English suitable for spoken playback.
        """
        if let context, !context.isEmpty {
            prompt += "\nCurrent context: \(context)"
        }

        let body: [String: Any] = [
            "model": DoubaoConfig.modelId,
            "input": [
                [
                    "role": "system",
                    "content": [
                        [
                            "type": "input_text",
                            "text": prompt
                        ]
                    ]
                ],
                [
                    "role": "user",
                    "content": [
                        [
                            "type": "input_text",
                            "text": question
                        ]
                    ]
                ]
            ],
            "max_output_tokens": 500,
            "temperature": 0.4
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw VisionError.networkError("Invalid response")
        }

        guard httpResponse.statusCode == 200 else {
            if httpResponse.statusCode == 401 {
                throw VisionError.authenticationFailed
            }
            let message = String(data: data, encoding: .utf8) ?? "No error details"
            throw VisionError.serverError(httpResponse.statusCode, message)
        }

        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            let raw = String(data: data, encoding: .utf8) ?? "Non-text response"
            throw VisionError.parsingFailed(raw)
        }

        guard let content = parseResponsesOutput(json) else {
            let raw = String(data: data, encoding: .utf8) ?? "\(json)"
            throw VisionError.parsingFailed(raw)
        }

        return content
    }

    private func parseResponsesOutput(_ json: [String: Any]) -> String? {
        if let outputText = json["output_text"] as? String, !outputText.isEmpty {
            return outputText
        }

        if let choices = json["choices"] as? [[String: Any]] {
            let joined = choices
                .compactMap { choice -> String? in
                    if let message = choice["message"] {
                        return extractText(from: message)
                    }
                    return extractText(from: choice)
                }
                .joined(separator: "\n")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if !joined.isEmpty {
                return joined
            }
        }

        if let output = json["output"] as? [[String: Any]] {
            let textParts = output.compactMap { item -> String? in
                if let content = item["content"] {
                    return extractText(from: content)
                }
                if let text = item["text"] as? String {
                    return text
                }
                if let outputText = item["output_text"] as? String {
                    return outputText
                }
                return nil
            }

            let joined = textParts.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if !joined.isEmpty {
                return joined
            }
        }

        if let output = json["output"] {
            return extractText(from: output)
        }

        if let message = json["message"] {
            return extractText(from: message)
        }

        if let content = json["content"] {
            return extractText(from: content)
        }

        return nil
    }

    private func extractText(from value: Any) -> String? {
        if let string = value as? String {
            let trimmed = string.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        }

        if let array = value as? [Any] {
            let joined = array
                .compactMap { extractText(from: $0) }
                .joined(separator: "\n")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return joined.isEmpty ? nil : joined
        }

        guard let dictionary = value as? [String: Any] else {
            return nil
        }

        for key in ["output_text", "text", "content"] {
            if let nested = dictionary[key],
               let text = extractText(from: nested) {
                return text
            }
        }

        if let message = dictionary["message"] as? [String: Any],
           let text = extractText(from: message) {
            return text
        }

        return nil
    }

    // MARK: - Private image compression
    private func compressImage(_ image: UIImage) -> Data? {
        let maxSize: CGFloat = 1024
        let scale = min(maxSize / image.size.width, maxSize / image.size.height, 1.0)
        let newSize = CGSize(width: image.size.width * scale, height: image.size.height * scale)

        UIGraphicsBeginImageContextWithOptions(newSize, false, 1.0)
        image.draw(in: CGRect(origin: .zero, size: newSize))
        let resized = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        return resized?.jpegData(compressionQuality: 0.7)
    }

    private func formatError(_ error: Error) -> String {
        if let visionError = error as? VisionError {
            return visionError.userMessage
        }
        return "Analysis failed: \(error.localizedDescription)"
    }
}

// MARK: - Image analysis errors
enum VisionError: Error {
    case notConfigured
    case invalidURL
    case networkError(String)
    case authenticationFailed
    case serverError(Int, String)
    case parsingFailed(String)
    case imageProcessingFailed

    var userMessage: String {
        switch self {
        case .notConfigured:
            return "Configure a Doubao API key in Settings first"
        case .invalidURL:
            return "The API address is invalid"
        case .networkError(let msg):
            return "Network error: \(msg)"
        case .authenticationFailed:
            return "The API key is invalid. Check Settings"
        case .serverError(let code, let message):
            return "Server error (\(code)): \(message)"
        case .parsingFailed(let raw):
            let compact = raw
                .replacingOccurrences(of: "\n", with: " ")
                .replacingOccurrences(of: "\r", with: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let preview = String(compact.prefix(180))
            return "Failed to parse the response. Received: \(preview)"
        case .imageProcessingFailed:
            return "Image processing failed"
        }
    }
}
