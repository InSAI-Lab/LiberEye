# LiberEye

LiberEye coordinates speech and wrist haptics for assistive navigation. A phone relays camera or glasses frames to a perception backend, then delivers the speech and Bluetooth wrist cues selected by Event-Priority Multimodal Coordination (EPMC).

The implementation follows Algorithm 1, equations (2) and (3), and Table 1 of *LiberEye: Event-Priority Coordination of Speech and Wrist Haptics for Assistive Navigation*.

## Components

- [Backend](backend/README.md): perception, EPMC, authenticated HTTP API and deployment configuration.
- [iOS app](ios/README.md): phone camera, cloud relay, wrist control and optional licensed glasses integration.
- [Wrist firmware](firmware/libereye_wrist/README.md): nRF52840 and DRV2605L reference implementation, wiring and flashing instructions.

## Quick start

Use Python 3.11 or 3.12:

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -c constraints.txt '.[dev,hardware]'
python scripts/configure_cloud.py
python scripts/run_cloud.py
```

The server listens on `127.0.0.1:8080`. The configuration script creates a private `.env` with an API token. See the [backend guide](backend/README.md) for model and OCR setup, and the [deployment guide](backend/docs/cloud-deployment.md) for server, domain and app settings.

## Documentation

- [Algorithm and paper correspondence](docs/algorithm.md)
- [API and wrist protocol](docs/api.md)
- [Development, testing and source packaging](docs/development.md)

## Citation and licensing

See [CITATION.cff](CITATION.cff) for citation metadata and [third-party notices](THIRD_PARTY_NOTICES.md) for dependency terms. No redistribution license for the project source has been specified.
