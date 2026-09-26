# LiberEye backend

Python backend for the paper's deterministic EPMC policy. The production API routes use `EPMCCoordinator`; `MobilityOrchestrator` and the static web UI remain legacy demonstration interfaces.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -c constraints.txt '.[dev,hardware]'
python scripts/configure_cloud.py
python scripts/run_cloud.py
```

See [cloud deployment](docs/cloud-deployment.md) for Docker, HTTPS, model configuration, health checks and phone integration. See the repository [README](../README.md) for firmware, iOS, paper correspondence and release instructions.

```bash
python -m pytest tests
python ../scripts/validate_epmc.py
```

Dependencies have one definition in `pyproject.toml`. `constraints.txt` pins the CPU dependency versions. Optional `hardware` installs BLE/serial clients; optional `vision` installs Ultralytics. Missing trained weights leave the default integration demo in heuristic mode. Configure `LIBEREYE_REQUIRE_MODELS=1` to reject media inference when required models are unavailable.

Install Tesseract for OCR. The Docker image includes the English and simplified Chinese language data.

## Local demonstration

Start the local web interface from this directory:

```bash
python -m libereye.server --port 8012
```

Open `http://127.0.0.1:8012`. Scenario buttons use synthetic inputs defined in [scenarios.py](libereye/scenarios.py); if the server is unavailable, the page uses scripted local examples. Media uploads use the configured perception pipeline and display its model or heuristic sources. Both server paths on this page use the legacy `MobilityOrchestrator`, not the production EPMC API.

The interface shows categorical plan priority, selected wrist cues, speech requests and optional-description state. These are generated software outputs. Motor intensity is an ordinal command, not a risk probability, and the legacy `cognitive_load` API field contains heuristic modality weights rather than measured participant load. The page does not display these values as percentages or connect to a wristband.

## Paper and validation

The associated manuscript is *LiberEye: Event-Priority Coordination of Speech and Wrist Haptics for Assistive Navigation* by Shicheng Li, Jiuhan Zhang, Fengjiao Yang and Jiaming Zhang. Citation metadata is provided in the repository's `CITATION.cff`.

[EPMC implementation](libereye/epmc.py) and [coordination tests](tests/test_epmc.py) cover cue priority, supervisory stop, and speech admission. [Wrist timing tests](tests/test_wrist_haptics.py) check the software timing table. Run the test commands above and `python ../scripts/validate_epmc.py` for exhaustive policy checks and synthetic replay. The repository's `docs/algorithm.md` maps the paper equations, Algorithm 1 and Table 1 to source files.

For study reproduction, use the original study records and analysis protocol.
