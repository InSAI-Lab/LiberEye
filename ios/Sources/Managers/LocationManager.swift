//
//  LocationManager.swift
//  LiberEye
//
//  Location and compass heading
//

import Foundation
import CoreLocation
import MapKit
import Combine
import SwiftUI

@MainActor
class LocationManager: NSObject, ObservableObject {

    // MARK: - Published state
    @Published var currentLocation: UserLocation = .unknown
    @Published var authorizationStatus: CLAuthorizationStatus = .notDetermined
    @Published var locationError: String? = nil
    @Published var isLocationAvailable: Bool = false
    @Published var headingDegrees: Double = 0
    @Published var compassDirection: CompassDirection = .north
    @Published var speedMPS: Double = 0

    // MARK: - Private state
    private let locationManager = CLLocationManager()
    private var lastGeocodedLocation: CLLocation?
    private var geocodeDebounceTask: Task<Void, Never>?

    // MARK: - Initialization
    override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.distanceFilter = 5.0
        locationManager.headingFilter = 5.0
    }

    // MARK: - Requesting permission and starting location updates
    func requestPermissionAndStart() {
        guard !AppRuntime.isRunningForPreviews else { return }
        switch locationManager.authorizationStatus {
        case .notDetermined:
            locationManager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            startTracking()
        case .denied, .restricted:
            locationError = "Location permission is denied. Enable it in Settings."
        @unknown default:
            break
        }
    }

    func startTracking() {
        locationManager.startUpdatingLocation()
        if CLLocationManager.headingAvailable() {
            locationManager.startUpdatingHeading()
        }
        isLocationAvailable = true
    }

    func stopTracking() {
        locationManager.stopUpdatingLocation()
        locationManager.stopUpdatingHeading()
    }

    // MARK: - Reverse geocoding
    func reverseGeocode(_ location: CLLocation) async {
        if let last = lastGeocodedLocation,
           location.distance(from: last) < 50 { return }

        lastGeocodedLocation = location
        geocodeDebounceTask?.cancel()

        geocodeDebounceTask = Task { @MainActor in
            do {
                let geocoder = CLGeocoder()
                let placemarks = try await geocoder.reverseGeocodeLocation(location)
                guard !Task.isCancelled else { return }
                if let placemark = placemarks.first {
                    let address = self.buildAddressString(from: placemark)
                    self.updateAddress(address)
                }
            } catch {
                // Retain the last address if geocoding fails.
            }
        }
    }

    private func buildAddressString(from placemark: CLPlacemark) -> String {
        var parts: [String] = []
        if let city = placemark.locality { parts.append(city) }
        if let subLocality = placemark.subLocality { parts.append(subLocality) }
        if let street = placemark.thoroughfare { parts.append(street) }
        if let name = placemark.name, !parts.contains(name) { parts.append(name) }
        return parts.isEmpty ? "Unknown location" : parts.joined(separator: " ")
    }

    private func updateAddress(_ address: String) {
        let loc = currentLocation
        currentLocation = UserLocation(
            latitude: loc.latitude,
            longitude: loc.longitude,
            accuracy: loc.accuracy,
            address: address,
            heading: loc.heading,
            compassDirection: loc.compassDirection
        )
    }

    // MARK: - Spoken location descriptions
    var voiceLocationDescription: String {
        let dir = compassDirection.rawValue
        let addr = currentLocation.address
        let speed = speedMPS > 0.5 ? String(format: ", walking at approximately %.1f meters per second", speedMPS) : ""
        return "Facing \(dir), at \(addr)\(speed)."
    }

    var voiceHeadingOnly: String {
        return "Facing \(compassDirection.rawValue)."
    }
}

// MARK: - CLLocationManagerDelegate
extension LocationManager: CLLocationManagerDelegate {

    nonisolated func locationManager(_ manager: CLLocationManager,
                                      didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }

        Task { @MainActor [weak self] in
            guard let self else { return }
            let direction = CompassDirection.from(degrees: self.headingDegrees)
            self.currentLocation = UserLocation(
                latitude: location.coordinate.latitude,
                longitude: location.coordinate.longitude,
                accuracy: location.horizontalAccuracy,
                address: self.currentLocation.address,
                heading: self.headingDegrees,
                compassDirection: direction
            )
            self.speedMPS = max(0, location.speed)
            self.locationError = nil
            await self.reverseGeocode(location)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager,
                                      didUpdateHeading newHeading: CLHeading) {
        let degrees = newHeading.magneticHeading
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.headingDegrees = degrees
            self.compassDirection = CompassDirection.from(degrees: degrees)
            let loc = self.currentLocation
            self.currentLocation = UserLocation(
                latitude: loc.latitude,
                longitude: loc.longitude,
                accuracy: loc.accuracy,
                address: loc.address,
                heading: degrees,
                compassDirection: self.compassDirection
            )
        }
    }

    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.authorizationStatus = status
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                self.startTracking()
                self.locationError = nil
            case .denied, .restricted:
                self.locationError = "Location permission is denied. Enable it in Settings."
                self.isLocationAvailable = false
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            if let clError = error as? CLError, clError.code == .denied {
                self.locationError = "Location permission denied"
            } else {
                self.locationError = "Location update failed: \(error.localizedDescription)"
            }
        }
    }
}
