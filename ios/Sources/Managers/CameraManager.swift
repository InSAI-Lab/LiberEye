//
//  CameraManager.swift
//  LiberEye
//
//  Phone camera capture
//  Stop the phone camera when using connected glasses to conserve power.
//

import Foundation
@preconcurrency import AVFoundation
import UIKit
import SwiftUI
import Combine

// MARK: - UIKit camera preview layer
class CameraPreviewView: UIView {
    override class var layerClass: AnyClass {
        return AVCaptureVideoPreviewLayer.self
    }

    var previewLayer: AVCaptureVideoPreviewLayer {
        return layer as! AVCaptureVideoPreviewLayer
    }
}

// MARK: - SwiftUI camera preview
struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> CameraPreviewView {
        let view = CameraPreviewView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        // Use videoRotationAngle in place of deprecated videoOrientation.
        if let connection = view.previewLayer.connection,
           connection.isVideoRotationAngleSupported(90) {
            connection.videoRotationAngle = 90
        }
        return view
    }

    func updateUIView(_ uiView: CameraPreviewView, context: Context) {
        uiView.previewLayer.session = session
    }
}

// MARK: - Camera manager
@MainActor
class CameraManager: NSObject, ObservableObject {

    @Published var isRunning: Bool = false
    @Published var capturedImage: UIImage? = nil
    @Published var authorizationStatus: AVAuthorizationStatus = .notDetermined
    @Published var error: String? = nil

    // Capture objects are accessed by AVFoundation callbacks outside the main actor.
    nonisolated(unsafe) let session = AVCaptureSession()
    nonisolated(unsafe) private var photoOutput = AVCapturePhotoOutput()
    private var captureCompletion: ((UIImage?) -> Void)? = nil

    // MARK: - Permission checks
    func checkPermissions() async {
        guard !AppRuntime.isRunningForPreviews else { return }
        let status = AVCaptureDevice.authorizationStatus(for: .video)

        switch status {
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            authorizationStatus = granted ? .authorized : .denied
            if granted { await setupSession() }
        case .authorized:
            authorizationStatus = .authorized
            await setupSession()
        case .denied, .restricted:
            authorizationStatus = status
            error = "Camera permission is denied. Enable it in Settings."
        @unknown default:
            break
        }
    }

    // MARK: - Camera session configuration
    private func setupSession() async {
        // Configure the capture session on a background queue.
        let captureSession = self.session
        let output = self.photoOutput

        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                captureSession.beginConfiguration()
                captureSession.sessionPreset = .photo

                // Attach the rear camera input.
                guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera,
                                                           for: .video,
                                                           position: .back),
                      let input = try? AVCaptureDeviceInput(device: camera) else {
                    captureSession.commitConfiguration()
                    continuation.resume()
                    return
                }

                if captureSession.canAddInput(input) {
                    captureSession.addInput(input)
                }

                // Attach the photo output.
                if captureSession.canAddOutput(output) {
                    captureSession.addOutput(output)
                }

                captureSession.commitConfiguration()
                continuation.resume()
            }
        }

        // Publish configuration errors on the main actor.
        if session.inputs.isEmpty {
            error = "The camera is unavailable"
        }
    }

    // MARK: - Starting and stopping capture
    func startSession() {
        guard !AppRuntime.isRunningForPreviews else { return }
        guard authorizationStatus == .authorized else { return }
        guard !session.isRunning else { return }

        let captureSession = self.session
        DispatchQueue.global(qos: .userInitiated).async {
            captureSession.startRunning()
            DispatchQueue.main.async { [weak self] in
                self?.isRunning = true
            }
        }
    }

    /// Stop camera capture when switching to glasses.
    func stopSession() {
        guard session.isRunning else { return }

        let captureSession = self.session
        DispatchQueue.global(qos: .background).async {
            captureSession.stopRunning()
            DispatchQueue.main.async { [weak self] in
                self?.isRunning = false
            }
        }
    }

    // MARK: - Photo capture
    func capturePhoto(completion: @escaping (UIImage?) -> Void) {
        guard isRunning else {
            completion(nil)
            return
        }

        guard let connection = photoOutput.connection(with: .video),
              connection.isActive,
              connection.isEnabled else {
            completion(nil)
            return
        }

        captureCompletion = completion
        let settings = AVCapturePhotoSettings()
        settings.flashMode = .auto
        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    // MARK: - Asynchronous photo capture
    func capturePhotoAsync() async -> UIImage? {
        return await withCheckedContinuation { continuation in
            capturePhoto { image in
                continuation.resume(returning: image)
            }
        }
    }
}

// MARK: - AVCapturePhotoCaptureDelegate
extension CameraManager: AVCapturePhotoCaptureDelegate {

    nonisolated func photoOutput(_ output: AVCapturePhotoOutput,
                                  didFinishProcessingPhoto photo: AVCapturePhoto,
                                  error: Error?) {
        guard error == nil,
              let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            Task { @MainActor in
                captureCompletion?(nil)
                captureCompletion = nil
            }
            return
        }

        // Normalize image orientation.
        let correctedImage = image.fixedOrientation()

        Task { @MainActor in
            capturedImage = correctedImage
            captureCompletion?(correctedImage)
            captureCompletion = nil
        }
    }
}

// MARK: - UIImage orientation normalization
extension UIImage {
    nonisolated func fixedOrientation() -> UIImage {
        guard imageOrientation != .up else { return self }

        UIGraphicsBeginImageContextWithOptions(size, false, scale)
        draw(in: CGRect(origin: .zero, size: size))
        let normalizedImage = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        return normalizedImage ?? self
    }
}
