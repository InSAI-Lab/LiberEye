# LiberEye: Event-Priority Coordination of Speech and Wrist Haptics for Assistive Navigation

Shicheng Li, Jiuhan Zhang, Fengjiao Yang, Jiaming Zhang

Hunan University

## Abstract

Concurrent visual events can generate competing spoken messages in wearable navigation, placing urgent action guidance behind optional scene descriptions. We present LiberEye, a wearable system that coordinates wrist cue selection and scene description admission using our Event Priority Multimodal Coordination (EPMC) algorithm. Backend perception modules produce structured mobility events, from which EPMC selects one of seven wrist patterns and determines whether descriptive speech remains eligible. During warnings or critical proximity, EPMC excludes optional descriptions from the assistance plan while keeping concise action instructions eligible. The system integrates camera glasses, a networked backend, smartphone speech, and a Bluetooth wrist band. In an exploratory study, four blind adults completed supervised outdoor navigation tasks. Mean NASA TLX scores were 50.8 for app speech, 42.5 for coordinated speech and haptics, and 39.2 for the full interface. The corresponding mean near miss counts were 1.8, 0.8, and 0.5. The coordinated configurations showed lower mean workload and fewer observed near misses than app speech alone.

## System and method

<p align="center">
  <img src="docs/images/libereye_prototype.png" width="47%" alt="LiberEye wearable prototype with glasses, phone, wrist band, and white cane">
  <img src="docs/images/libereye_epmc.png" width="47%" alt="EPMC selection of wrist cues and scene description admission">
</p>

Camera glasses acquire images, and a smartphone relays them to a networked backend. Perception modules emit mobility events with a source, severity, confidence, candidate modalities, and a short recommendation. The backend returns an assistance plan that the phone dispatches as speech and Bluetooth wrist commands.

EPMC selects the highest priority wrist cue under `W3 > W2 > W1 > D4 > D3 > D2 > D1`. A supervisory override selects W3 and a stop instruction. W1, W2, W3, D4, or danger severity withholds optional scene descriptions. Concise action instructions remain eligible. The seven commanded wrist patterns and implementation mapping are documented in [Algorithm and cue timing](docs/algorithm.md).

## User study

Four blind adults completed an approximately 300 m outdoor route with sidewalks, tactile paving, a signalized crossing, and target search. Participants retained their white canes, and a mobility specialist or trained safety researcher stayed close enough to intervene. Each participant tried the four common walking conditions in counterbalanced order. C0 used a cane only, C1 used app speech, and C2 combined speech and wrist haptics without app detail during walking. C3 added full interface status and fallback interaction.

<p align="center">
  <img src="docs/images/libereye_field_study.png" width="65%" alt="Four blind participants using white canes during supervised outdoor sessions">
</p>

Common task means and standard deviations for four participants are shown below. Incident values are event counts.

| Measure | C0 | C1 | C2 | C3 |
| --- | ---: | ---: | ---: | ---: |
| Collisions | 0.8 ± 0.5 | 0.5 ± 0.6 | 0 | 0 |
| Near misses | 2.3 ± 0.5 | 1.8 ± 0.5 | 0.8 ± 0.5 | 0.5 ± 0.6 |
| Safety interventions | 1.3 ± 0.5 | 0.8 ± 0.5 | 0.3 ± 0.5 | 0 |
| NASA TLX | 57.5 ± 13.7 | 50.8 ± 12.1 | 42.5 ± 10.4 | 39.2 ± 22.0 |
| SUS | N/A | 73.8 ± 7.5 | 80.6 ± 4.8 | 83.8 ± 3.2 |
| Confidence | 3.0 ± 0.7 | 3.5 ± 0.6 | 4.2 ± 0.5 | 4.5 ± 0.4 |
| Speech suppressions | N/A | 0 | 6.8 ± 1.7 | 7.5 ± 1.3 |
| Haptic preemptions | N/A | N/A | 4.5 ± 1.3 | 5.3 ± 1.0 |

Speech suppression and haptic preemption counts summarize EPMC decisions in the assistance plan.

## Components

- [Backend](backend/README.md): perception, EPMC, authenticated HTTP API and deployment configuration.
- [iOS app](ios/README.md): phone camera, cloud relay, wrist control and optional licensed glasses integration.
- [Wrist firmware](firmware/libereye_wrist/README.md): nRF52840 and DRV2605L reference implementation, wiring and flashing instructions.

## Getting started

The repository contains the [backend](backend/README.md), [iOS app](ios/README.md), and [wrist firmware](firmware/libereye_wrist/README.md). To run the backend locally, use Python 3.11 or 3.12.

```bash
git clone https://github.com/InSAI-Lab/LiberEye.git
cd LiberEye/backend
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -c constraints.txt .
python scripts/configure_cloud.py
python scripts/run_cloud.py
```

The API listens on `127.0.0.1:8080`. Without configured perception weights, media analysis uses heuristic fallback. Model configuration and deployment instructions are in the [backend guide](backend/README.md) and [deployment guide](backend/docs/cloud-deployment.md).

No redistribution license has been specified for the project source. Dependency terms are listed in [third party notices](THIRD_PARTY_NOTICES.md).

## Citation

```bibtex
@unpublished{li2026libereye,
  author = {Li, Shicheng and Zhang, Jiuhan and Yang, Fengjiao and Zhang, Jiaming},
  title = {{LiberEye}: Event-Priority Coordination of Speech and Wrist Haptics for Assistive Navigation},
  year = {2026},
  note = {Under submission to ICASSP 2027}
}
```

[BibTeX](CITATION.bib) · [Citation metadata](CITATION.cff)

## Discussion

<p align="center">
  <a href="https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=fb8ice2e-8db6-446f-a96a-bf589ecb59dc&amp;qr_code=true">
    <img src="docs/images/libereye_feishu.png" width="380" alt="LiberEye Feishu discussion group QR code">
  </a>
</p>

[Join the Feishu group](https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=fb8ice2e-8db6-446f-a96a-bf589ecb59dc&qr_code=true)
