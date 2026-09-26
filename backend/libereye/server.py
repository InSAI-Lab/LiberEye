from __future__ import annotations

import argparse
import cgi
import json
import tempfile
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .epmc import EPMCCoordinator
from .media_analyzer import MediaAnalyzer
from .mobile_contract import mobile_response, perception_evidence
from .models import PerceptionFrame
from .mobility_coordinator import MobilityOrchestrator
from .smartphone_relay import format_smartphone_plan


class LiberEyeRequestHandler(SimpleHTTPRequestHandler):
    orchestrator = MobilityOrchestrator()
    media_analyzer = MediaAnalyzer()
    epmc = EPMCCoordinator()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/health", "/api/health"}:
            self._send_json({"status": "ok", "service": "libereye-server"})
            return
        if parsed.path == "/api/scenarios":
            self._send_json({"scenarios": self.orchestrator.available_scenarios()})
            return
        if parsed.path == "/api/epmc/metrics":
            samples = self.epmc.alert_latency_ms_samples
            median_lat = sorted(samples)[len(samples) // 2] if samples else 0.0
            self._send_json({
                "speech_suppression_count": self.epmc.speech_suppression_count,
                "haptic_preemption_count": self.epmc.haptic_preemption_count,
                "total_updates": self.epmc.total_updates,
                "median_alert_latency_ms": round(median_lat, 2),
                "fsm_phase": self.epmc.fsm.current_phase,
            })
            return
        if parsed.path == "/api/analyze":
            scenario_id = parse_qs(parsed.query).get("scenario", ["sidewalk"])[0]
            try:
                plan = self.orchestrator.analyze_scenario(scenario_id)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=404)
                return
            self._send_json(asdict(plan))
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api/live", "/api/mobile/analyze-perception"}:
            try:
                payload = self._read_json_body()
                frame = PerceptionFrame(**payload)
                plan = self.orchestrator.analyze_perception(frame)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            if parsed.path == "/api/mobile/analyze-perception":
                evidence = perception_evidence(asdict(frame), source="phone_structured")
                self._send_json(mobile_response(plan, evidence=evidence, source="phone_structured"))
            else:
                self._send_json(asdict(plan))
            return
        if parsed.path == "/api/epmc/analyze-perception":
            try:
                payload = self._read_json_body()
                frame = PerceptionFrame(**payload)
                plan = self.epmc.analyze_perception(frame)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            evidence = perception_evidence(asdict(frame), source="epmc_perception")
            self._send_json(format_smartphone_plan(plan, evidence=evidence, source="epmc"))
            return
        if parsed.path in {"/api/analyze-media", "/api/mobile/analyze-media"}:
            try:
                media_path, target_query = self._read_media_upload()
                frame, evidence = self.media_analyzer.analyze_file(media_path, target_query=target_query)
                plan = self.orchestrator.analyze_perception(frame)
            except (TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            finally:
                if "media_path" in locals():
                    Path(media_path).unlink(missing_ok=True)
            if parsed.path == "/api/mobile/analyze-media":
                self._send_json(mobile_response(plan, evidence=evidence, source="phone_media"))
            else:
                payload = asdict(plan)
                payload["media_evidence"] = evidence
                self._send_json(payload)
            return
        self._send_json({"error": "Not found"}, status=404)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def _read_media_upload(self) -> tuple[Path, str | None]:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        file_item = form["media"] if "media" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            raise ValueError("Missing uploaded file field: media")
        suffix = Path(file_item.filename).suffix.lower()
        target_query = form.getfirst("target_query") or None
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            while True:
                chunk = file_item.file.read(1024 * 1024)
                if not chunk:
                    break
                tmp.write(chunk)
            return Path(tmp.name), target_query

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8000, directory: Path | None = None) -> None:
    web_root = directory or Path(__file__).resolve().parents[1]
    handler = lambda *args, **kwargs: LiberEyeRequestHandler(*args, directory=str(web_root), **kwargs)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"LiberEye demo running at http://{host}:{port}")
    print("API: /api/analyze?scenario=sidewalk")
    print("Media API: POST /api/analyze-media with multipart field 'media'")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LiberEye local multi-agent demo server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
