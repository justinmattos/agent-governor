import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from govd import audit, config
from govd.policy.engine import ALLOW, Ctx, Decision, Engine, Event
from govd.policy.rules import default_rules
from govd.state import LockTable, SessionPlans

STARTED_AT = time.time()
LOCKS = LockTable()
PLANS = SessionPlans()
ENGINE = Engine(default_rules())


def _event_from(payload):
    return Event(
        agent=payload.get("agent", "unknown"),
        event=payload.get("event", ""),
        tool=payload.get("tool"),
        raw_tool_name=payload.get("raw_tool_name", ""),
        input=payload.get("input") or {},
        cwd=payload.get("cwd", ""),
        session_id=payload.get("session_id", ""),
        meta=payload.get("meta") or {},
    )


def evaluate(payload):
    event = _event_from(payload)
    if event.event == "session_end":
        LOCKS.release_session(event.session_id)
        PLANS.clear(event.session_id)
        return Decision(decision=ALLOW, rule="session_end")
    decision = ENGINE.evaluate(event, Ctx(locks=LOCKS, plans=PLANS))
    try:
        audit.record(event, decision)
    except Exception:
        pass
    return decision


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/v1/health":
            self._send(200, {
                "status": "ok",
                "version": config.VERSION,
                "pid": os.getpid(),
                "uptime_seconds": round(time.time() - STARTED_AT, 1),
                "rules": [r.name for r in ENGINE.rules],
            })
        elif self.path == "/v1/locks":
            self._send(200, {"held": LOCKS.snapshot()})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        # JSON-only: a browser cannot send this content type without a CORS
        # preflight, which this server never answers.
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self.close_connection = True
            self._send(415, {"error": "Content-Type must be application/json"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            self._send(400, {"error": "bad Content-Length"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}", strict=False)
        except Exception:
            self._send(200, {"decision": ALLOW, "reason": "", "additional_context": ""})
            return

        if self.path != "/v1/evaluate":
            self._send(404, {"error": "not found"})
            return

        try:
            decision = evaluate(payload)
        except Exception as exc:
            self._send(200, {
                "decision": ALLOW,
                "reason": "",
                "additional_context": "",
                "error": str(exc),
            })
            return

        self._send(200, {
            "decision": decision.decision,
            "reason": decision.reason,
            "additional_context": decision.context,
            "rules": decision.rule,
        })


def _write_runtime(port):
    config.ensure_home()
    with open(config.PORT_FILE, "w") as fh:
        fh.write(str(port))
    with open(config.PID_FILE, "w") as fh:
        fh.write(str(os.getpid()))


def main():
    port = config.DEFAULT_PORT
    server = ThreadingHTTPServer((config.HOST, port), Handler)
    _write_runtime(port)
    sys.stderr.write(f"govd {config.VERSION} listening on {config.HOST}:{port}\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for path in (config.PID_FILE, config.PORT_FILE):
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
