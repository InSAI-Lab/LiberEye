//
//  MiniCompassNeedle.swift
//  LiberEye
//

import SwiftUI

struct MiniCompassNeedle: View {
    let heading: Double

    var body: some View {
        ZStack {
            Arrow(pointingUp: true)
                .fill(Color.red)
                .frame(width: 7, height: 26)
                .offset(y: -13)

            Arrow(pointingUp: false)
                .fill(Color.gray.opacity(0.42))
                .frame(width: 7, height: 22)
                .offset(y: 11)
        }
        .rotationEffect(.degrees(heading))
        .animation(.easeInOut(duration: 0.3), value: heading)
    }
}
