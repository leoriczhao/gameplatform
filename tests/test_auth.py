"""Auth API tests: register / login / me / guest."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

_tmp = tempfile.TemporaryDirectory()
os.environ["SCORES_DB"] = str(Path(_tmp.name) / "scores.db")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402

client = TestClient(main.app)


def test_register_and_me_roundtrip():
    r = client.post("/api/v1/auth/register",
                    json={"username": "alice001", "password": "password123"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["user"]["username"] == "alice001"
    assert data["user"]["role"] == "user"
    token = data["token"]

    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "alice001"

    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401  # no token -> guest rejected


def test_duplicate_username_rejected():
    client.post("/api/v1/auth/register",
                json={"username": "bob002", "password": "password123"})
    r = client.post("/api/v1/auth/register",
                    json={"username": "bob002", "password": "password456"})
    assert r.status_code == 400


def test_bad_username_or_password_rejected():
    r = client.post("/api/v1/auth/register",
                    json={"username": "x", "password": "password123"})
    assert r.status_code == 422  # username too short (pydantic)
    r = client.post("/api/v1/auth/register",
                    json={"username": "valid_user", "password": "short"})
    assert r.status_code == 422  # password too short


def test_login_flow():
    client.post("/api/v1/auth/register",
                json={"username": "carol003", "password": "password123"})
    r = client.post("/api/v1/auth/login",
                    json={"username": "carol003", "password": "wrongpass9"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/login",
                    json={"username": "carol003", "password": "password123"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "carol003"
    assert r.json()["token"]


def test_guest_identity():
    r = client.post("/api/v1/auth/guest")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "guest"
    assert r.json()["token"]  # per-browser guest token (uuid identity)
    # the guest token resolves as a (token) guest principal
    from auth import principal_from_request
    from fastapi import Request as _R
    # (thin check: token decodes to a guest-* subject)
    from auth import decode_token
    payload = decode_token(r.json()["token"])
    assert payload["sub"].startswith("guest-")


def test_tampered_token_rejected():
    token = client.post("/api/v1/auth/register",
                        json={"username": "dave004", "password": "password123"}
                        ).json()["token"]
    bad = token[:-4] + "AAAA"
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401
