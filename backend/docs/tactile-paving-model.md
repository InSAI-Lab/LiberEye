# Tactile paving model integration and training

The LiberEye vision backend supports a dedicated tactile paving model. The general model detects people, vehicles and other objects; tactile paving results are merged into semantic regions. Before training, install the backend's `vision` dependencies and prepare a YOLO-format dataset and base weights with appropriate usage permissions.

## Dataset layout

```text
datasets/tactile_paving/
  data.yaml
  train/images
  train/labels
  valid/images
  valid/labels
  test/images
  test/labels
```

Use `tactile_paving` as the class label. The backend can convert detection boxes into regions or compute region coverage from segmentation masks.

## Local training

Run from `backend/`:

```bash
python scripts/train_tactile_model.py \
  --data datasets/tactile_paving/data.yaml \
  --model yolo26n.pt \
  --epochs 80 \
  --imgsz 640 \
  --batch 8 \
  --device cpu
```

Set `--device` to `cpu`, a CUDA device index or `mps`, as supported by your environment. Training writes weights to `runs/tactile/tactile_yolo/weights/best.pt`.

## Cloud configuration

Copy the trained weights to `models/tactile.pt` on the server and set these values in the server's `.env`:

```dotenv
LIBEREYE_ENABLE_STRONG_VISION=1
LIBEREYE_TACTILE_MODEL=/models/tactile.pt
```

These paths apply to Docker deployments. When running Python directly, enter the actual weight paths on your server. See [cloud deployment](cloud-deployment.md) for other model, authentication and startup settings.

For the Roboflow Hosted API, set `LIBEREYE_ROBOFLOW_API_KEY` and `LIBEREYE_ROBOFLOW_TACTILE_MODEL` in the same `.env`. Use the model identifier provided on the selected model page.

Successful training and model loading confirm that the integration works. Use independent test images representative of the deployment environment to evaluate perception when tactile paving is obstructed, interrupted or left behind.
