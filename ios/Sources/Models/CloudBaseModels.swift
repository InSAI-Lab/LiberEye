//
//  CloudBaseModels.swift
//  LiberEye
//
//  CloudBase authentication, token and error response models.
//

import Foundation

enum CloudBaseDefaults {
    static let envId = ""
    static let region = "ap-shanghai"
    static let publishableKey = ""
}

// MARK: - CloudBase configuration
struct CloudBaseConfig: Codable {
    let envId: String
    let region: String   // Mainland China: ap-shanghai; international: ap-singapore
    let baseURL: String  // API gateway address

    var apiBaseURL: String {
        if region == "ap-shanghai" {
            return "https://\(envId).api.tcloudbasegateway.com"
        } else {
            return "https://\(envId).api.intl.tcloudbasegateway.com"
        }
    }

    var authBaseURL: String {
        return "https://\(envId).ap-shanghai.tcb-api.tencentcloudapi.com/auth/v1"
    }

    static var placeholder: CloudBaseConfig {
        CloudBaseConfig(envId: "", region: "ap-shanghai", baseURL: "")
    }
}

// MARK: - Login response
struct CloudBaseLoginResponse: Codable {
    let accessToken: String?
    let refreshToken: String?
    let expiresIn: Int?      // Seconds
    let loginType: String?
    let uid: String?
    let token: String?        // Some endpoints return token instead of access_token.

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
        case loginType = "login_type"
        case uid
        case token
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // Accept alternative response field names.
        if let accessToken = try? container.decode(String.self, forKey: .accessToken) {
            self.accessToken = accessToken
        } else if let token = try? container.decode(String.self, forKey: .token) {
            self.accessToken = token
        } else {
            self.accessToken = nil
        }

        if let refreshToken = try? container.decode(String.self, forKey: .refreshToken) {
            self.refreshToken = refreshToken
        } else {
            // Check alternative token fields.
            let singleKeyContainer = try decoder.singleValueContainer()
            if let rawDict = try? singleKeyContainer.decode([String: AnyCodable].self),
               let rt = rawDict["refresh_token"]?.value as? String {
                self.refreshToken = rt
            } else {
                self.refreshToken = nil
            }
        }

        self.expiresIn = try container.decodeIfPresent(Int.self, forKey: .expiresIn)
        self.loginType = try container.decodeIfPresent(String.self, forKey: .loginType)
        self.uid = try container.decodeIfPresent(String.self, forKey: .uid)
        self.token = try container.decodeIfPresent(String.self, forKey: .token)
    }
}

// A helper for arbitrary JSON values.
struct AnyCodable: Codable {
    let value: Any

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let intVal = try? container.decode(Int.self) {
            value = intVal
        } else if let doubleVal = try? container.decode(Double.self) {
            value = doubleVal
        } else if let boolVal = try? container.decode(Bool.self) {
            value = boolVal
        } else if let stringVal = try? container.decode(String.self) {
            value = stringVal
        } else if let arrayVal = try? container.decode([AnyCodable].self) {
            value = arrayVal.map { $0.value }
        } else if let dictVal = try? container.decode([String: AnyCodable].self) {
            value = dictVal.mapValues { $0.value }
        } else {
            value = NSNull()
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        if let intVal = value as? Int {
            try container.encode(intVal)
        } else if let doubleVal = value as? Double {
            try container.encode(doubleVal)
        } else if let boolVal = value as? Bool {
            try container.encode(boolVal)
        } else if let stringVal = value as? String {
            try container.encode(stringVal)
        } else {
            try container.encodeNil()
        }
    }
}

// MARK: - Token refresh response
struct CloudBaseTokenRefreshResponse: Codable {
    let accessToken: String
    let refreshToken: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case refreshToken = "refresh_token"
        case expiresIn = "expires_in"
    }
}

// MARK: - Verification code request response
struct CloudBaseVerificationResponse: Codable {
    let verificationId: String?
    let expiresIn: Int?
    let requestId: String?

    enum CodingKeys: String, CodingKey {
        case verificationId = "verification_id"
        case expiresIn = "expires_in"
        case requestId = "request_id"
    }

    // Accept optional fields in different response formats.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // Accept alternative response field names.
        self.verificationId = try? container.decode(String.self, forKey: .verificationId)
        self.expiresIn = try? container.decode(Int.self, forKey: .expiresIn)
        self.requestId = try? container.decode(String.self, forKey: .requestId)
    }
}

// MARK: - Verification code validation response
struct CloudBaseVerifyResponse: Codable {
    let verificationToken: String?
    let requestId: String?

    enum CodingKeys: String, CodingKey {
        case verificationToken = "verification_token"
        case requestId = "request_id"
    }

    // Accept optional fields in different response formats.
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.verificationToken = try container.decodeIfPresent(String.self, forKey: .verificationToken)
        self.requestId = try container.decodeIfPresent(String.self, forKey: .requestId)
    }
}

// MARK: - User information
struct CloudBaseUser: Codable, Identifiable {
    let id: String
    let phoneNumber: String?
    let username: String?
    let name: String?
    let email: String?
    let createdAt: Date?
    let lastLoginAt: Date?

    enum CodingKeys: String, CodingKey {
        case id = "uid"
        case phoneNumber = "phone_number"
        case username
        case name
        case email
        case createdAt = "created_at"
        case lastLoginAt = "last_login_time"
    }
}

// MARK: - Generic cloud function response
struct CloudBaseFunctionResponse<T: Codable>: Codable {
    let code: Int?
    let message: String?
    let data: T?
    let requestId: String?

    enum CodingKeys: String, CodingKey {
        case code
        case message
        case data
        case requestId = "request_id"
    }

    var isSuccess: Bool {
        return code == 0 || code == nil
    }
}

// MARK: - API error response
struct CloudBaseErrorResponse: Codable {
    let code: String
    let message: String
    let requestId: String?

    enum CodingKeys: String, CodingKey {
        case code
        case message
        case requestId = "request_id"
    }
}

// MARK: - User profile data
struct UserProfile: Codable, Identifiable {
    var id: String { odId }
    let odId: String            // OpenID
    var phoneNumber: String?
    var displayName: String?
    var voiceSpeed: Double       // Speech rate: 0.5 to 2.0
    var voicePitch: Double       // Speech pitch: 0.5 to 2.0
    var perceptionMode: String   // glasses / phone
    var vibrationEnabled: Bool
    var doubaoApiKey: String?   // Encrypted storage
    var createdAt: Date
    var updatedAt: Date

    static var `default`: UserProfile {
        UserProfile(
            odId: "",
            phoneNumber: nil,
            displayName: "User",
            voiceSpeed: 1.0,
            voicePitch: 1.0,
            perceptionMode: "phone",
            vibrationEnabled: true,
            doubaoApiKey: nil,
            createdAt: Date(),
            updatedAt: Date()
        )
    }
}

// MARK: - Scene analysis history
struct SceneAnalysisRecord: Codable, Identifiable {
    let id: Int?
    let odId: String
    let mode: String            // SceneAnalysisMode.rawValue
    let imageUrl: String?       // Cloud image path
    let localImageHash: String? // Local image hash
    let resultText: String      // Image analysis result
    let processingTime: Double  // Processing time in seconds
    let latitude: Double?
    let longitude: Double?
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case odId = "_openid"
        case mode
        case imageUrl = "image_url"
        case localImageHash = "local_image_hash"
        case resultText = "result_text"
        case processingTime = "processing_time"
        case latitude
        case longitude
        case createdAt = "created_at"
    }
}

// MARK: - Obstacle reports
struct ObstacleReport: Codable, Identifiable {
    let id: Int?
    let odId: String
    let direction: String
    let distance: Double
    let description: String
    let dangerLevel: Int        // DangerLevel.rawValue
    let latitude: Double?
    let longitude: Double?
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case odId = "_openid"
        case direction
        case distance
        case description
        case dangerLevel = "danger_level"
        case latitude
        case longitude
        case createdAt = "created_at"
    }
}

// MARK: - Device pairings
struct DevicePairing: Codable, Identifiable {
    let id: Int?
    let odId: String
    let deviceName: String
    let deviceType: String      // glasses / bracelet
    let deviceUUID: String
    var lastConnectedAt: Date?
    var isDefault: Bool
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case id
        case odId = "_openid"
        case deviceName = "device_name"
        case deviceType = "device_type"
        case deviceUUID = "device_uuid"
        case lastConnectedAt = "last_connected_at"
        case isDefault = "is_default"
        case createdAt = "created_at"
    }
}
