# Vision Test Fixtures

This directory holds optional local images for domain vision integration tests.
Images are not committed because the source datasets carry their own licenses.

## Layout

```text
tests/fixtures/vision/
  tactile/
    sample_01.jpg
  crosswalk/
    sample_01.jpg
  traffic_light/
    sample_01.jpg
```

## Sources

Use `scripts/download_vision_testsets.py` for dataset links and setup notes.
Copy a few representative test images into the matching directory above:

- `tactile/`: tactile paving, braille blocks, or warning blocks
- `crosswalk/`: zebra crossings or pedestrian crossings
- `traffic_light/`: red, yellow, and green traffic lights

Tests skip real-image cases when these files are absent, while mock and synthetic
frame tests continue to run.
