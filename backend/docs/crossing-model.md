# Crossing model integration and training

The LiberEye vision backend supports separate crosswalk and traffic-light models. Before training, install the backend's `vision` dependencies and prepare a YOLO-format dataset and base weights with appropriate usage permissions.

## Local training

Run from `backend/`:

```bash
python scripts/train_crossing_model.py \
  --data datasets/crosswalk/data.yaml \
  --model yolo26n.pt \
  --epochs 80 \
  --imgsz 640 \
  --batch 8 \
  --device cpu \
  --name crosswalk_yolo

python scripts/train_crossing_model.py \
  --data datasets/traffic_light/data.yaml \
  --model yolo26n.pt \
  --epochs 80 \
  --imgsz 640 \
  --batch 8 \
  --device cpu \
  --name traffic_light_yolo
```

Set `--device` to `cpu`, a CUDA device index or `mps`, as supported by your environment. Training writes weights to `runs/crossing/crosswalk_yolo/weights/best.pt` and `runs/crossing/traffic_light_yolo/weights/best.pt`, respectively.

## Cloud configuration

Copy the trained weights to `models/` on the server and set these values in the server's `.env`:

```dotenv
LIBEREYE_ENABLE_STRONG_VISION=1
LIBEREYE_CROSSWALK_MODEL=/models/crosswalk.pt
LIBEREYE_TRAFFIC_LIGHT_MODEL=/models/traffic_light.pt
```

These paths apply to Docker deployments. When running Python directly, enter the actual weight paths on your server. See [cloud deployment](cloud-deployment.md) for other model, authentication and startup settings.

For the Roboflow Hosted API, set `LIBEREYE_ROBOFLOW_API_KEY`, `LIBEREYE_ROBOFLOW_CROSSWALK_MODEL` and `LIBEREYE_ROBOFLOW_TRAFFIC_LIGHT_MODEL` in the same `.env`. Use the model identifiers provided on the selected model pages.

## Class mapping

The labels `crosswalk`, `zebra_crossing` and `pedestrian_crossing` map to `crosswalk`.

Traffic-light labels support `red`, `green`, `yellow`, `red_light`, `green_light`, `yellow_light`, `traffic_light_red`, `traffic_light_green` and `traffic_light_yellow`. Each maps to its corresponding traffic-light state.

Successful training and model loading confirm that the integration works. Evaluate perception results on independent test images representative of the deployment environment.
