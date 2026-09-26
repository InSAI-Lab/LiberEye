//
//  AppRuntime.swift
//  LiberEye
//

import Foundation
import Security

enum AppRuntime {
    static var allowsInsecureCloud: Bool {
        ProcessInfo.processInfo.environment["LIBEREYE_ALLOW_INSECURE_HTTP"] == "1"
    }

    static var isRunningForPreviews: Bool {
        ProcessInfo.processInfo.environment["XCODE_RUNNING_FOR_PREVIEWS"] == "1"
    }
}

/// Store credentials in Keychain and migrate existing installations out of UserDefaults.
enum AppSecretStore {
    private static let service = "org.libereye.credentials"

    static func read(_ key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var item: CFTypeRef?
        if SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
           let data = item as? Data {
            return String(data: data, encoding: .utf8)
        }
        if let legacy = UserDefaults.standard.string(forKey: key), write(legacy, for: key) {
            return legacy
        }
        return nil
    }

    @discardableResult
    static func write(_ value: String, for key: String) -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]
        if value.isEmpty {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { return false }
        } else {
            let data = Data(value.utf8)
            let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
            if status == errSecItemNotFound {
                var attributes = query
                attributes[kSecValueData as String] = data
                attributes[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
                guard SecItemAdd(attributes as CFDictionary, nil) == errSecSuccess else { return false }
            } else if status != errSecSuccess {
                return false
            }
        }
        UserDefaults.standard.removeObject(forKey: key)
        return true
    }
}
