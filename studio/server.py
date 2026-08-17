#!/usr/bin/env python3
"""Localhost studio for the documentary pipeline.

    python studio/server.py          # then open http://127.0.0.1:8765

Standard library only, so it runs with nothing installed. Gemini is optional and
used only for voice beats; everything else — structure extraction, validation,
assembly — is local and deterministic.

Binds to 127.0.0.1 deliberately. Nothing here is hardened for exposure to a
network, and the slot documents contain unpublished research.
"""

from __future__ import annotations

import json
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from extractor import analyse, compare  # noqa: E402
from generator import build, voice_prompt, BEAT_PLAN  # noqa: E402
from schema import gate_candidate, validate  # noqa: E402

HOST, PORT = "127.0.0.1", 8765
MAX_BODY = 8 * 1024 * 1024  # transcripts are large; JSON slot docs are not


def _findings(result) -> list[dict]:
    return [{"severity": f.severity.value, "path": f.path, "message": f.message}
            for f in result.findings]


class Handler(BaseHTTPRequestHandler):
    server_version = "DocStudio/1.0"

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write(f"  {self.command} {self.path} → {args[1] if len(args) > 1 else ''}\n")

    # --- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError(f"body too large ({length} bytes)")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    # --- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            page = HERE / "index.html"
            if not page.exists():
                return self._json(500, {"error": "index.html missing"})
            return self._send(200, page.read_bytes(), "text/html; charset=utf-8")

        if self.path == "/api/beats":
            return self._json(200, {
                "plan": {str(n): {"name": name, "share": share}
                         for n, (name, share) in BEAT_PLAN.items()}
            })

        if self.path == "/api/corpus":
            profile = HERE / "corpus_profile.json"
            if profile.exists():
                return self._json(200, json.loads(profile.read_text()))
            return self._json(200, {})

        if self.path == "/api/example":
            example = HERE / "examples" / "buffalo_creek_1972.json"
            if example.exists():
                return self._json(200, json.loads(example.read_text()))
            return self._json(404, {"error": "example not found"})

        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
        except Exception as exc:
            return self._json(400, {"error": f"bad request body: {exc}"})

        try:
            if self.path == "/api/analyse":
                texts = payload.get("transcripts") or {}
                if isinstance(texts, str):
                    texts = {"pasted": texts}
                if not texts:
                    return self._json(400, {"error": "no transcripts supplied"})
                results = {name: analyse(text) for name, text in texts.items() if text.strip()}
                if not results:
                    return self._json(400, {"error": "transcripts were empty"})
                return self._json(200, {
                    "analyses": {k: v.to_dict() for k, v in results.items()},
                    "profile": compare(results),
                })

            if self.path == "/api/validate":
                result = validate(payload.get("slots") or {})
                return self._json(200, {
                    "ok": result.ok,
                    "findings": _findings(result),
                    "report": result.report(),
                })

            if self.path == "/api/gate":
                result = gate_candidate(payload.get("candidate") or {})
                return self._json(200, {
                    "verdict": "greenlight" if result.ok else "reject",
                    "findings": _findings(result),
                    "report": result.report(),
                })

            if self.path == "/api/build":
                slots = payload.get("slots") or {}
                voice = {int(k): v for k, v in (payload.get("voice") or {}).items()}
                minutes = float(payload.get("target_minutes") or 25)
                use_model = bool(payload.get("use_model"))
                script = build(slots, target_minutes=minutes, voice=voice, use_model=use_model)

                if script.validation and not script.validation.ok:
                    return self._json(200, {
                        "ok": False,
                        "report": script.validation.report(),
                        "findings": _findings(script.validation),
                    })

                return self._json(200, {
                    "ok": True,
                    "word_count": script.word_count,
                    "runtime_minutes": script.runtime_minutes,
                    "target_words": int(minutes * 150),
                    "annotated": script.annotated(),
                    "narration": script.narration(),
                    "sources": script.source_appendix(),
                    "findings": _findings(script.validation) if script.validation else [],
                    "beats": [
                        {"beat": b.beat, "name": b.name, "kind": b.kind,
                         "words": b.actual_words, "target": b.target_words}
                        for b in script.beats
                    ],
                })

            if self.path == "/api/prompt":
                beat = int(payload.get("beat") or 1)
                slots = payload.get("slots") or {}
                words = int(payload.get("target_words") or 100)
                return self._json(200, {"prompt": voice_prompt(beat, slots, words)})

            return self._json(404, {"error": "not found"})

        except Exception as exc:
            traceback.print_exc()
            return self._json(500, {"error": f"{type(exc).__name__}: {exc}"})


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"\n  Documentary Studio")
    print(f"  → http://{HOST}:{PORT}\n")
    print("  Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
