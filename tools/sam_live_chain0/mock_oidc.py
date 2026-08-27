"""Loopback-only OIDC fixture for SAM-LIVE-CHAIN0 clean replay.

This is test infrastructure. Keys are generated at process start and never used
outside the local run.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = os.getenv("OIDC_ISSUER", "http://127.0.0.1:18080")
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUB = KEY.public_key().public_numbers()


def b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


JWKS = {"keys": [{"kty": "RSA", "alg": "RS256", "use": "sig", "kid": "sam-live-chain0", "n": b64u(PUB.n), "e": b64u(PUB.e)}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(fmt % args, flush=True)

    def _json(self, status: int, body: dict) -> None:
        data = json.dumps(body, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/.well-known/openid-configuration":
            self._json(200, {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/auth", "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/keys"})
        elif self.path == "/keys":
            self._json(200, JWKS)
        else:
            self._json(200, {"ok": True})

    def do_POST(self) -> None:
        if self.path != "/token":
            self._json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        params = urllib.parse.parse_qs(self.rfile.read(length).decode())
        client_id = params.get("client_id", ["node-client"])[0]
        roles = ["sam:role:router"] if client_id == "router-client" else ["sam:role:node"]
        now = int(time.time())
        token = jwt.encode({"iss": ISSUER, "aud": "sam-mesh-audience", "sub": client_id, "iat": now, "exp": now + 3600, "roles": roles, "groups": ["sam-live-chain0"]}, KEY, algorithm="RS256", headers={"kid": "sam-live-chain0"})
        self._json(200, {"access_token": token, "id_token": token, "token_type": "Bearer", "expires_in": 3600})


if __name__ == "__main__":
    print(f"SAM-LIVE-CHAIN0 mock OIDC ready: {ISSUER}", flush=True)
    HTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
