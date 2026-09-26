//
//  LiquidGlassStyle.swift
//  LiberEye
//
//  Shared Liquid Glass styles.
//

import SwiftUI

// MARK: - Shared constants
enum LGStyle {
    /// Tab bar content height; the main tab bar handles the bottom safe area.
    static let tabBarHeight: CGFloat = 84
    /// Bottom overlay height to reserve for page content.
    static let tabBarAvoidanceHeight: CGFloat = 136
    /// Card corner radius.
    static let cardCornerRadius: CGFloat = 20
    /// Shared background gradient.
    static let backgroundGradient = LinearGradient(
        colors: [
            Color(red: 0.91, green: 0.96, blue: 1.0),   // Light ice blue.
            Color(red: 0.97, green: 0.99, blue: 1.0),   // Near white.
            Color.white
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

// MARK: - Gradient background modifier
struct LiquidGlassBackground: ViewModifier {
    func body(content: Content) -> some View {
        ZStack {
            LGStyle.backgroundGradient
                .ignoresSafeArea()
            content
        }
    }
}

// MARK: - Glass card modifier
struct GlassCard: ViewModifier {
    var cornerRadius: CGFloat = LGStyle.cardCornerRadius
    var material: Material = .ultraThinMaterial

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(material)
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius)
                            .fill(
                                LinearGradient(
                                    colors: [
                                        Color.white.opacity(0.34),
                                        Color.white.opacity(0.10),
                                        Color.white.opacity(0.04)
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius)
                            .stroke(Color.white.opacity(0.55), lineWidth: 1)
                    )
                    .shadow(color: Color.black.opacity(0.08), radius: 14, y: 4)
            )
    }
}

// MARK: - Glass capsule modifier for status labels
struct GlassCapsule: ViewModifier {
    var material: Material = .ultraThinMaterial

    func body(content: Content) -> some View {
        content
            .background(
                Capsule()
                    .fill(material)
                    .overlay(
                        Capsule()
                            .stroke(Color.white.opacity(0.5), lineWidth: 1)
                    )
            )
    }
}

// MARK: - Liquid Glass style for primary action buttons
struct GlassActionButton: ViewModifier {
    var color: Color
    var cornerRadius: CGFloat = 16

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(.ultraThinMaterial)
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius)
                            .fill(color.opacity(0.10))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius)
                            .stroke(
                                LinearGradient(
                                    colors: [color.opacity(0.55), color.opacity(0.20)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1.2
                            )
                    )
                    .shadow(color: color.opacity(0.12), radius: 6, y: 2)
            )
    }
}

// MARK: - View convenience modifiers
extension View {
    /// Apply the background gradient.
    func liquidGlassBackground() -> some View {
        modifier(LiquidGlassBackground())
    }

    /// Apply the glass card style.
    func glassCard(cornerRadius: CGFloat = LGStyle.cardCornerRadius,
                   material: Material = .ultraThinMaterial) -> some View {
        modifier(GlassCard(cornerRadius: cornerRadius, material: material))
    }

    /// Apply the glass capsule style.
    func glassCapsule(material: Material = .ultraThinMaterial) -> some View {
        modifier(GlassCapsule(material: material))
    }

    /// Apply the primary action button style.
    func glassActionButton(color: Color, cornerRadius: CGFloat = 16) -> some View {
        modifier(GlassActionButton(color: color, cornerRadius: cornerRadius))
    }

    /// Bottom content padding to clear the tab bar.
    func tabBarPadding(_ extra: CGFloat = 0) -> some View {
        self.padding(.bottom, LGStyle.tabBarAvoidanceHeight + extra)
    }

    /// Transparent glass page background for lists and forms.
    func liquidGlassSystemList() -> some View {
        self
            .scrollContentBackground(.hidden)
            .listStyle(.insetGrouped)
            .background(LGStyle.backgroundGradient.ignoresSafeArea())
    }
}
