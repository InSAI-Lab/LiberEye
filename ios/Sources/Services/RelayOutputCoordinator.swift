import Foundation

/// Execute only the output actions authorized by the cloud EPMC policy.
@MainActor
enum RelayOutputCoordinator {
    static func dispatch(_ plan: LiberEyeCloudPlan, bluetooth: BluetoothManager, speech: SpeechManager) {
        if bluetooth.canDeliverFeedback, let command = plan.authorizedHapticCommand {
            bluetooth.sendVibration(command)
        } else {
            bluetooth.stopVibration()
        }

        // voice_message is informational. It must never bypass should_speak or output_actions.
        for action in plan.authorizedSpeechActions {
            guard let message = action.message, !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { continue }
            let priority: SpeechManager.SpeechPriority
            switch (action.priority ?? plan.priority).lowercased() {
            case "danger": priority = .critical
            case "warn": priority = .high
            default: priority = .normal
            }
            speech.speak(message, priority: priority, interruptIfNeeded: action.interrupt ?? false)
        }
    }
}
