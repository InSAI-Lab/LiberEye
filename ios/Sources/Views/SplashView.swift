//
//  SplashView.swift
//  LiberEye
//
//  Splash screen with the application logo and tagline.
//

import SwiftUI

// MARK: - Splash screen
struct SplashView: View {
    @State private var opacity: Double = 0
    @State private var scale: Double = 0.85
    var onFinish: () -> Void

    var body: some View {
        ZStack {
            Color.white.ignoresSafeArea()

            VStack(spacing: 24) {
                Image("LiberEyeLaunchLogo")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 340, height: 340)
                    .accessibilityLabel("LiberEye")
            }
            .scaleEffect(scale)
            .opacity(opacity)
            .animation(.easeOut(duration: 0.6), value: opacity)
            .animation(.spring(response: 0.6, dampingFraction: 0.7), value: scale)
        }
        .onAppear {
            withAnimation {
                opacity = 1
                scale = 1
            }
            // Continue after 2 seconds.
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.2) {
                withAnimation(.easeInOut(duration: 0.4)) {
                    opacity = 0
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                    onFinish()
                }
            }
        }
    }
}

#Preview {
    SplashView(onFinish: {})
        .environmentObject(AuthManager.shared)
}
