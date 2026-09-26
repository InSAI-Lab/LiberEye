//
//  AppModels.swift
//  LiberEye
//
//  Core application data models.
//

import Foundation
import SwiftUI

// MARK: - Device connection state
enum DeviceConnectionState {
    case disconnected
    case scanning
    case connecting
    case connected

    var displayText: String {
        let language = AppLanguageManager.shared
        switch self {
        case .disconnected: return language.text("disconnected")
        case .scanning: return language.text("scanning")
        case .connecting: return language.text("connecting")
        case .connected: return language.text("connected")
        }
    }

    var color: Color {
        switch self {
        case .disconnected: return .gray
        case .scanning: return .yellow
        case .connecting: return .orange
        case .connected: return .green
        }
    }
}

// MARK: - Perception mode
enum PerceptionMode: String, CaseIterable {
    case glasses = "glasses"
    case phone = "phone"

    var icon: String {
        switch self {
        case .glasses: return "eyeglasses"
        case .phone: return "camera.fill"
        }
    }

    var description: String {
        let language = AppLanguageManager.shared
        switch self {
        case .glasses: return language.text("glasses_mode_desc")
        case .phone: return language.text("phone_mode_desc")
        }
    }

    var displayName: String {
        let language = AppLanguageManager.shared
        switch self {
        case .glasses: return language.text("glasses")
        case .phone: return language.text("phone_camera")
        }
    }
}

// MARK: - Danger levels
enum DangerLevel: Int, Comparable {
    case safe = 0        // Safe
    case low = 1         // Low risk (distant obstacle)
    case medium = 2      // Medium risk (midrange obstacle)
    case high = 3        // High risk (nearby obstacle)
    case critical = 4    // Critical risk (emergency stop)

    static func < (lhs: DangerLevel, rhs: DangerLevel) -> Bool {
        lhs.rawValue < rhs.rawValue
    }

    var displayText: String {
        let language = AppLanguageManager.shared
        switch self {
        case .safe: return language.text("safe")
        case .low: return language.text("caution")
        case .medium: return language.text("warning")
        case .high: return language.text("danger")
        case .critical: return language.text("critical")
        }
    }

    var color: Color {
        switch self {
        case .safe: return .green
        case .low: return .yellow
        case .medium: return .orange
        case .high: return .red
        case .critical: return Color(red: 0.8, green: 0, blue: 0)
        }
    }

    /// Band vibration interval in milliseconds; smaller values repeat more often.
    var vibrationInterval: Int {
        switch self {
        case .safe: return 0      // No vibration
        case .low: return 2000    // D1: every 2 seconds
        case .medium: return 1000 // D2: every 1 second
        case .high: return 500    // D3: every 0.5 seconds
        case .critical: return 250 // D4: every 0.25 seconds
        }
    }

    /// Vibration pattern description
    var vibrationDescription: String {
        let language = AppLanguageManager.shared
        switch self {
        case .safe: return language.text("no_vibration")
        case .low: return "D1: light 0.15 s pulse every 2 s (3 to 5 m)"
        case .medium: return "D2: light 0.15 s pulse every 1 s (1.5 to 3 m)"
        case .high: return "D3: medium 0.2 s pulse every 0.5 s (0.8 to 1.5 m)"
        case .critical: return "D4: medium 0.2 s pulse every 0.25 s (within 0.8 m)"
        }
    }
}

// MARK: - Obstacle information
struct ObstacleInfo: Identifiable, Equatable {
    let id = UUID()
    let direction: String        // Direction, such as ahead or ahead to the left.
    let distance: Double         // Distance in meters.
    let description: String      // Obstacle description.
    let dangerLevel: DangerLevel
    let timestamp: Date

    var voiceAlert: String {
        "\(description) \(String(format: "%.1f", distance)) meters \(direction). \(dangerLevel.displayText)"
    }
}

// MARK: - Direction
enum CompassDirection: String {
    case north = "north"
    case northeast = "northeast"
    case east = "east"
    case southeast = "southeast"
    case south = "south"
    case southwest = "southwest"
    case west = "west"
    case northwest = "northwest"

    static func from(degrees: Double) -> CompassDirection {
        let normalized = (degrees + 360).truncatingRemainder(dividingBy: 360)
        switch normalized {
        case 337.5...360, 0..<22.5: return .north
        case 22.5..<67.5: return .northeast
        case 67.5..<112.5: return .east
        case 112.5..<157.5: return .southeast
        case 157.5..<202.5: return .south
        case 202.5..<247.5: return .southwest
        case 247.5..<292.5: return .west
        case 292.5..<337.5: return .northwest
        default: return .north
        }
    }

    var icon: String {
        switch self {
        case .north: return "arrow.up"
        case .northeast: return "arrow.up.right"
        case .east: return "arrow.right"
        case .southeast: return "arrow.down.right"
        case .south: return "arrow.down"
        case .southwest: return "arrow.down.left"
        case .west: return "arrow.left"
        case .northwest: return "arrow.up.left"
        }
    }

    var displayText: String {
        let language = AppLanguageManager.shared
        switch self {
        case .north: return language.text("north")
        case .northeast: return language.text("northeast")
        case .east: return language.text("east")
        case .southeast: return language.text("southeast")
        case .south: return language.text("south")
        case .southwest: return language.text("southwest")
        case .west: return language.text("west")
        case .northwest: return language.text("northwest")
        }
    }
}

// MARK: - Scene analysis result
struct SceneAnalysis: Identifiable {
    let id = UUID()
    let rawText: String          // Recognized text.
    let sceneDescription: String // Scene description.
    let locationHint: String     // Location hint, such as a store name.
    let suggestions: [String]    // Suggested actions.
    let timestamp: Date

    static let empty = SceneAnalysis(
        rawText: "",
        sceneDescription: "",
        locationHint: "",
        suggestions: [],
        timestamp: Date()
    )
}

// MARK: - Bluetooth device types
enum BluetoothDeviceType {
    case glasses  // Glasses
    case bracelet // Vibration band
}

// MARK: - Bluetooth devices
struct BluetoothDevice: Identifiable {
    let id: UUID
    let name: String
    let type: BluetoothDeviceType
    var connectionState: DeviceConnectionState
    var signalStrength: Int  // RSSI value.

    var displayName: String {
        let language = AppLanguageManager.shared
        switch type {
        case .glasses: return "\(language.text("glasses")): \(name)"
        case .bracelet: return "\(language.text("vibration_bracelet")): \(name)"
        }
    }

    var typeIcon: String {
        switch type {
        case .glasses: return "eyeglasses"
        case .bracelet: return "applewatch"
        }
    }
}

// MARK: - User location
struct UserLocation {
    let latitude: Double
    let longitude: Double
    let accuracy: Double
    let address: String
    let heading: Double          // Heading in degrees (0 to 360).
    let compassDirection: CompassDirection

    static let unknown = UserLocation(
        latitude: 0, longitude: 0, accuracy: 0,
        address: AppLanguageManager.shared.text("getting_location"), heading: 0,
        compassDirection: .north
    )
}

// MARK: - Application features
enum AppFeature: String, CaseIterable {
    case navigation = "navigation"
    case obstacle = "obstacle"
    case sceneAnalysis = "sceneAnalysis"
    case deviceManager = "deviceManager"
    case settings = "settings"

    var icon: String {
        switch self {
        case .navigation: return "location.north.fill"
        case .obstacle: return "shield.fill"
        case .sceneAnalysis: return "sparkles"
        case .deviceManager: return "antenna.radiowaves.left.and.right"
        case .settings: return "gearshape.fill"
        }
    }

    var color: Color {
        switch self {
        case .navigation: return .blue
        case .obstacle: return .orange
        case .sceneAnalysis: return .purple
        case .deviceManager: return .teal
        case .settings: return .gray
        }
    }

    var accessibilityLabel: String {
        let language = AppLanguageManager.shared
        switch self {
        case .navigation: return language.text("navigation_accessibility")
        case .obstacle: return language.text("obstacle_accessibility")
        case .sceneAnalysis: return language.text("scene_analysis_accessibility")
        case .deviceManager: return language.text("device_manager_accessibility")
        case .settings: return language.text("settings_accessibility")
        }
    }

    var displayTitle: String {
        let language = AppLanguageManager.shared
        switch self {
        case .navigation: return language.text("navigation")
        case .obstacle: return language.text("obstacle_detection")
        case .sceneAnalysis: return language.text("scene_analysis")
        case .deviceManager: return language.text("device_manager")
        case .settings: return language.text("settings")
        }
    }
}
