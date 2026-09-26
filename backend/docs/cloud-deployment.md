# Cloud deployment

This release ships reader-managed deployment code and instructions. A live author-operated server is not part of the release deliverable. Readers choose a Linux cloud VM or laboratory Linux server with Docker Engine and the Compose plugin, then deploy the backend directory `backend`. The supported starting configuration is one server running one API process.


## Where each value goes

All file paths below are relative to `backend` on the reader's server.

| Item | Where to configure it | Value to supply |
| --- | --- | --- |
| Backend source | The reader's Linux server | Copy or clone the source, then work in this backend directory |
| Server address | The DNS provider's console | Point the chosen hostname's A record to the server's public IPv4 address; configure AAAA only if IPv6 also works |
| DNS hostname | `.env`, `LIBEREYE_DOMAIN` | Your hostname without `https://`, a port or a path |
| Certificate contact | `.env`, `ACME_EMAIL` | A contact email controlled by the operator |
| API credential | `.env`, `LIBEREYE_API_TOKEN` | Generated privately by `scripts/configure_cloud.py` |
| HTTPS routing | `deploy/Caddyfile` | Already reads `LIBEREYE_DOMAIN`; no hostname edit is needed here |
| Phone service address | App Settings > LiberEye Cloud > Server URL | `https://` followed by the same hostname |
| Phone credential | App Settings > LiberEye Cloud > Cloud access token | The exact `LIBEREYE_API_TOKEN` from the server |
| Trained weights | `models/` and model variables in `.env` | The reader's licensed weights, referenced as `/models/...` in the container |

The placeholder `libereye.example.org` is already used by the iOS code and is the shared example throughout these instructions. It is not a working service address. Replace it with a hostname you control. The GitHub repository URL downloads the source and is not an API Base URL. The separate CloudBase settings in the app are optional account-service settings, not the Python inference endpoint.

## First setup on the reader's server

After copying the source onto the server, run the following from its backend directory. Replace the example hostname and email first:

```bash
python3 scripts/configure_cloud.py \
  --domain libereye.example.org \
  --email maintainer@example.org
```

This is a configuration step only: it writes a private `.env` and creates `models/`. It does not create a server, purchase a domain, change DNS or start a service. It requires only the Python standard library. For Docker deployment, Docker installs the Python API dependencies inside the image. For direct Python execution, install the dependencies as shown in the repository README.

If `.env` already exists, the command preserves it and exits. Edit that existing file locally to set `LIBEREYE_DOMAIN` and `ACME_EMAIL`; preserve or deliberately rotate its token. Do not edit `.env.example` to store private deployment values.

## Local configuration

Run all commands from `backend` after installing the Python dependencies as shown in the repository README. Skip `configure_cloud.py` below if `.env` already exists.

```bash
python scripts/configure_cloud.py
python scripts/run_cloud.py
```

The generated `.env` is private, mode 0600 and excluded from Git. API authentication fails closed when the token is absent. For an explicitly unauthenticated loopback experiment only, set `LIBEREYE_ALLOW_INSECURE=1`. Docker always sets this value to zero. Do not embed real tokens in source or example files.

## Docker CPU integration demo

Install Docker Engine and the Compose plugin on the server, copy the source, then run. Skip `configure_cloud.py` if `.env` was already generated in the first setup step:

```bash
python scripts/configure_cloud.py
docker compose config --quiet
docker compose up -d --build
curl --fail http://127.0.0.1:8080/health
```

For the optional authenticated smoke check, first install the backend Python dependencies on the host as shown in the repository README, then run `python scripts/smoke_cloud.py`. That script reads `.env` and sends authenticated requests without printing the token. The API port binds to loopback. The service runs as a non-root user with a read-only root filesystem, bounded temporary storage, dropped capabilities and rotated logs. CPU inference defaults to the heuristic demo. A liveness status of `ok` does not certify perception accuracy.

## HTTPS

In the DNS console for a domain you control, point the selected hostname at the reader's server. Permit inbound TCP 80 and 443 in both the cloud security group and the server firewall. Configure `LIBEREYE_DOMAIN` and `ACME_EMAIL` in the server's private `.env`. Keep API port 8080 closed to the Internet.

For example, replace these illustrative values with your own:

```dotenv
LIBEREYE_DOMAIN=libereye.example.org
ACME_EMAIL=maintainer@example.org
```

`compose.https.yaml` passes these variables to Caddy, and `deploy/Caddyfile` reads `{$LIBEREYE_DOMAIN}` and `{$ACME_EMAIL}`. Readers do not need to change a domain literal in the backend, Caddyfile or Swift sources. Only readers who choose to bring their server online execute the following commands:

```bash
docker compose -f compose.yaml -f deploy/compose.https.yaml config --quiet
docker compose -f compose.yaml -f deploy/compose.https.yaml up -d --build
```

The configuration follows [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https). Caddy obtains and renews certificates when DNS and network access are correct. Certificate state persists in Docker volumes. Do not remove those volumes during ordinary upgrades. On the phone, open **Settings > LiberEye Cloud**, enable **Enable cloud analysis**, enter `https://libereye.example.org` in **Server URL** after replacing the example hostname, and paste the server token into **Access token**. Do not append `/api/mobile/analyze-media`; the app adds that route. **Save settings** stores the configuration locally without contacting the server. After deploying, use **Test service** to make an authenticated `/ready` request. The app distinguishes model readiness from basic heuristic mode. Send a test image to check the inference path and use a connected wristband to check device feedback. The included token scheme is appropriate for a controlled research deployment. Multi-user public registration requires a separate account and token issuance service.

## Trained perception

Obtain weights with suitable permissions and place them in `models/`. The directory is mounted read-only at `/models`. Set the four variables `LIBEREYE_YOLO_MODEL`, `LIBEREYE_TACTILE_MODEL`, `LIBEREYE_CROSSWALK_MODEL`, `LIBEREYE_TRAFFIC_LIGHT_MODEL` to existing `/models/...` files. Set `INSTALL_VISION=1`, `LIBEREYE_ENABLE_STRONG_VISION=1` and `LIBEREYE_REQUIRE_MODELS=1`. SAM refinement is optional. Do not use default automatic downloads in a reproducible deployment; record the source, license and SHA-256 of each weight file.

`/ready` and media requests return 503 if required models are absent or model loading reports errors. `/health` reports heuristic versus model mode separately. Evaluate the configured models with representative inputs from the intended camera and environment.

An optional NVIDIA server override is provided:

```bash
docker compose -f compose.yaml -f deploy/compose.gpu.yaml -f deploy/compose.https.yaml up -d --build
```

It requires [Docker Compose 2.30.0 or newer](https://docs.docker.com/reference/compose-file/services/#gpus), NVIDIA Container Toolkit, a compatible host driver and a matching CUDA-enabled PyTorch installation. Run inference on the target NVIDIA server, measure memory use and adjust `LIBEREYE_MEMORY_LIMIT` for the selected models. The GPU override permits a writable root filesystem for model-library caches.

## State, load and privacy

Use a random `X-LiberEye-Session` per navigation session. EPMC scene state and counters are isolated by that ID. Missing IDs give stateless requests. Sessions expire after 900 seconds of inactivity, with a default cap of 256. Expired entries are removed lazily on the next session access. These values are configurable. One process is required because state lives in memory. A restart loses session history. Do not add replicas or Uvicorn workers without shared state or session-aware routing.

Inference runs outside the event loop. A busy model returns 503 so phones can submit a fresh frame instead of accumulating obsolete camera frames. The service caps request bodies at 16 MiB and decoded images at 16 million pixels. The proxy also caps request bodies at 16 MB. Camera uploads use temporary files and are deleted after success or failure. Uvicorn access logging is off by default. Model errors are not exposed in public liveness responses.

The single-process deployment follows the [FastAPI container guidance](https://fastapi.tiangolo.com/deployment/docker/). Tune resources with representative videos and real models before field use. A single client can still monopolize a shared research token; public deployment needs per-account quotas at the gateway.

## Operations

```bash
docker compose logs --tail=100 api
docker compose restart api
docker compose down
```

Keep a prior image tag and its compatible configuration for rollback. Rotate API credentials through the private `.env` and update phones before restarting. Never publish the existing local `.env`. Cloud interruption must trigger the phone's connection warning and stop wrist output.
