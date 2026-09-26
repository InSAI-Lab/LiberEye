# Third-party components

Dependencies retain their respective licenses. Refer to the license accompanying each installed version or model weight for its terms.

| Component | Use | Distribution |
| --- | --- | --- |
| FastAPI, Uvicorn, Pydantic | HTTP API and validation | Python dependencies |
| NumPy, OpenCV, Pillow, Requests, python-multipart, python-dotenv | Media, transport and configuration | Python dependencies |
| Tesseract and pytesseract | OCR | Python wrapper; engine and language packs installed separately or in Docker |
| Ultralytics and model checkpoints | Optional perception | Optional dependency; weights supplied separately under their own terms |
| PyTorch | Optional model runtime | Installed with the chosen model stack |
| Bleak, PySerial | Desktop device clients | Optional Python dependencies |
| Adafruit nRF52 BSP, TinyUSB, DRV2605 library, BusIO | Wrist firmware | Installed by the firmware dependency script |
| QCSDK, JLAudioUnitKit, JLLogHelper, HeyCyan headers and licensing script | Optional glasses integration | Proprietary vendor dependencies, excluded from the source archive |

Ultralytics offers AGPL and commercial licensing; the applicable terms depend on the selected software, weights and use. Obtain authorized glasses SDK files from the supplier before building `ios/LiberEyeGlasses.xcodeproj`. The default `ios/LiberEye.xcodeproj` builds without them.

The mobility context planner draws on the contextual navigation approach of WalkVLM. Original third-party notices in vendor materials remain applicable. Project naming does not transfer ownership of dependencies or their licenses.
