//
//  NavigationLocationView.swift
//  LiberEye
//
//  Navigation view with GPS location and compass heading.
//

import SwiftUI
import MapKit

struct NavigationLocationView: View {
    @EnvironmentObject var locationManager: LocationManager
    @EnvironmentObject var bluetoothManager: BluetoothManager
    @EnvironmentObject var speechManager: SpeechManager
    @EnvironmentObject var languageManager: AppLanguageManager

    @State private var position: MapCameraPosition = .userLocation(fallback: .automatic)

    var body: some View {
        NavigationStack {
            ZStack {
                LGStyle.backgroundGradient.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 16) {
                        // Prioritize speech controls commonly used by blind and low-vision users.
                        voiceActionButtons

                        // Map and compass
                        mapCompassCard

                        // Location information card
                        locationCard
                    }
                    .padding(.horizontal)
                    .tabBarPadding()
                }
            }
            .navigationTitle(languageManager.text("navigation"))
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    // MARK: - Map and compass card
    private var mapCompassCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 12) {
                Text(languageManager.text("location_map"))
                    .font(.headline)
                Spacer()
                Text(String(format: "%.0f°", locationManager.headingDegrees))
                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal)
            .padding(.top)

            ZStack(alignment: .topLeading) {
                Map(position: $position) {
                    UserAnnotation()
                }
                .mapControls {
                    MapUserLocationButton()
                }
                .frame(height: 180)
                .clipShape(RoundedRectangle(cornerRadius: 12))

                miniCompass
                    .padding(10)
            }
            .padding(.horizontal)

            HStack(spacing: 10) {
                Image(systemName: locationManager.compassDirection.icon)
                    .font(.title3)
                    .foregroundColor(.blue)

                VStack(alignment: .leading, spacing: 2) {
                    Text(languageManager.format("facing_direction", locationManager.compassDirection.displayText))
                        .font(.system(size: 19, weight: .bold, design: .rounded))
                    if locationManager.speedMPS > 0.5 {
                        Text(languageManager.format("walking_speed", locationManager.speedMPS))
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }

                Spacer()

                Button(action: {
                    speechManager.speakDirection(locationManager.compassDirection)
                }) {
                    Image(systemName: "speaker.wave.2.fill")
                        .font(.title3)
                        .foregroundColor(.blue)
                        .padding(10)
                        .background(Circle().fill(Color.blue.opacity(0.12)))
                }
                .accessibilityLabel(languageManager.text("speak_direction"))
            }
            .padding(.horizontal)
            .padding(.bottom)
        }
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 20)
                        .stroke(Color.white.opacity(0.55), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.06), radius: 8)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(languageManager.format("heading_accessibility", locationManager.compassDirection.displayText, Int(locationManager.headingDegrees)))
    }

    private var miniCompass: some View {
        ZStack {
            Circle()
                .fill(.regularMaterial)
                .frame(width: 72, height: 72)
                .shadow(color: .black.opacity(0.10), radius: 7, y: 3)

            CompassTicksView()
                .frame(width: 58, height: 58)
                .opacity(0.55)

            ForEach(compassLabels.filter { [0, 90, 180, 270].contains(Int($0.1)) }, id: \.0) { (label, angle) in
                Text(label)
                    .font(.system(size: 9, weight: .bold))
                    .foregroundColor(angle == 0 ? .red : .primary)
                    .offset(compassLabelOffset(angle: angle, radius: 28))
                    .padding(1)
                    .background(Circle().fill(.regularMaterial.opacity(0.75)))
            }

            MiniCompassNeedle(heading: locationManager.headingDegrees)
                .frame(width: 26, height: 42)

            Circle()
                .fill(Color.primary)
                .frame(width: 4, height: 4)
        }
        .frame(width: 76, height: 76)
        .accessibilityHidden(true)
    }

    // MARK: - Location information card
    private var locationCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "location.fill")
                    .foregroundColor(.blue)
                Text(languageManager.text("current_location"))
                    .font(.headline)
                Spacer()
                if locationManager.isLocationAvailable {
                    Label(languageManager.text("locating"), systemImage: "dot.radiowaves.up.forward")
                        .font(.caption)
                        .foregroundColor(.green)
                } else {
                    Label(languageManager.text("not_located"), systemImage: "location.slash")
                        .font(.caption)
                        .foregroundColor(.orange)
                }
            }

            if let error = locationManager.locationError {
                Text(error)
                    .font(.subheadline)
                    .foregroundColor(.red)
            } else {
                Text(locationManager.currentLocation.address)
                    .font(.system(size: 17, weight: .medium))
                    .lineLimit(2)

                HStack(spacing: 20) {
                    locationCoordItem(
                        label: languageManager.text("latitude"),
                        value: String(format: "%.4f°", locationManager.currentLocation.latitude)
                    )
                    locationCoordItem(
                        label: languageManager.text("longitude"),
                        value: String(format: "%.4f°", locationManager.currentLocation.longitude)
                    )
                    locationCoordItem(
                        label: languageManager.text("accuracy"),
                        value: String(format: "±%.0fm", locationManager.currentLocation.accuracy)
                    )
                }
                .padding(.top, 4)
            }
        }
        .padding()
        .glassCard()
        .accessibilityElement(children: .combine)
        .accessibilityLabel(locationManager.voiceLocationDescription)
    }

    // MARK: - Speech controls
    private var voiceActionButtons: some View {
        VStack(spacing: 10) {
            Button(action: {
                speechManager.speak(locationManager.voiceLocationDescription, priority: .normal)
            }) {
                HStack {
                    Image(systemName: "location.north.line.fill")
                        .font(.system(size: 24))
                    Text(languageManager.text("speak_full_location"))
                        .font(.system(size: 18, weight: .semibold))
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundColor(.secondary)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 18)
                .glassActionButton(color: .blue)
                .foregroundColor(.blue)
            }
            .accessibilityLabel(languageManager.text("speak_location_accessibility"))

            Button(action: {
                speechManager.speak(locationManager.voiceHeadingOnly, priority: .normal)
                bluetoothManager.sendNavigationVibration()
            }) {
                HStack {
                    Image(systemName: "arrow.triangle.turn.up.right.circle.fill")
                        .font(.system(size: 24))
                    Text(languageManager.text("speak_heading_with_vibration"))
                        .font(.system(size: 18, weight: .semibold))
                    Spacer()
                    Image(systemName: "chevron.right")
                        .foregroundColor(.secondary)
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 18)
                .glassActionButton(color: .green)
                .foregroundColor(.green)
            }
            .accessibilityLabel(languageManager.text("speak_heading_accessibility"))
        }
    }

    // MARK: - Helpers
    private func locationCoordItem(label: String, value: String) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(.system(size: 13, weight: .semibold, design: .monospaced))
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
    }

    private var compassLabels: [(String, Double)] {
        [
            (languageManager.text("north"), 0),
            (languageManager.text("northeast"), 45),
            (languageManager.text("east"), 90),
            (languageManager.text("southeast"), 135),
            (languageManager.text("south"), 180),
            (languageManager.text("southwest"), 225),
            (languageManager.text("west"), 270),
            (languageManager.text("northwest"), 315)
        ]
    }

    private func compassLabelOffset(angle: Double, radius: CGFloat) -> CGSize {
        let radians = (angle - 90) * .pi / 180
        return CGSize(
            width: radius * cos(radians),
            height: radius * sin(radians)
        )
    }
}

struct Arrow: Shape {
    let pointingUp: Bool

    func path(in rect: CGRect) -> Path {
        var path = Path()
        if pointingUp {
            path.move(to: CGPoint(x: rect.midX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
            path.addLine(to: CGPoint(x: rect.midX, y: rect.maxY * 0.7))
            path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        } else {
            path.move(to: CGPoint(x: rect.midX, y: rect.maxY))
            path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))
            path.addLine(to: CGPoint(x: rect.midX, y: rect.minY + rect.height * 0.3))
            path.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
        }
        path.closeSubpath()
        return path
    }
}

// MARK: - Compass ticks
struct CompassTicksView: View {
    var body: some View {
        Canvas { context, size in
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let radius = min(size.width, size.height) / 2

            for i in 0..<72 {
                let angle = Double(i) * 5.0 * .pi / 180.0
                let isMainTick = i % 18 == 0
                let isSmallTick = i % 9 == 0
                let tickLength: CGFloat = isMainTick ? 14 : (isSmallTick ? 10 : 6)
                let lineWidth: CGFloat = isMainTick ? 2 : 1

                let outerX = center.x + (radius - 8) * sin(angle)
                let outerY = center.y - (radius - 8) * cos(angle)
                let innerX = center.x + (radius - 8 - tickLength) * sin(angle)
                let innerY = center.y - (radius - 8 - tickLength) * cos(angle)

                var path = Path()
                path.move(to: CGPoint(x: outerX, y: outerY))
                path.addLine(to: CGPoint(x: innerX, y: innerY))

                context.stroke(path,
                               with: .color(isMainTick ? .primary : .secondary.opacity(0.5)),
                               lineWidth: lineWidth)
            }
        }
    }
}
