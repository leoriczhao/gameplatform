#!/usr/bin/env python3
"""Create a Cloudflare named tunnel for Stream end-to-end.

Adapted from the snake-web script. Env vars:
  TUNNEL_HOSTNAME  default games.cree1p.com
  TUNNEL_NAME      default games-tunnel
  TUNNEL_SERVICE   default http://gameplatform-web:8080
  TOKEN_OUT        default ~/gameplatform/.tunnel-token
  CLOUDFLARE_API_TOKEN / CF_TOKEN_FILE  (required)

Idempotent: reuses an existing tunnel/DNS record instead of failing.
Never prints secrets.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
HOSTNAME = os.environ.get("TUNNEL_HOSTNAME", "games.cree1p.com")
TUNNEL_NAME = os.environ.get("TUNNEL_NAME", "games-tunnel")
SERVICE = os.environ.get("TUNNEL_SERVICE", "http://gameplatform-web:8080")
TOKEN_OUT = os.path.expanduser(
    os.environ.get("TUNNEL_TOKEN_OUT", "~/gameplatform/.tunnel-token"))

token = None
if os.environ.get("CF_TOKEN_FILE"):
    with open(os.environ["CF_TOKEN_FILE"]) as f:
        token = f.read().strip()
elif os.environ.get("CLOUDFLARE_API_TOKEN"):
    token = os.environ["CLOUDFLARE_API_TOKEN"].strip()
if not token:
    print("need CF_TOKEN_FILE or CLOUDFLARE_API_TOKEN", file=sys.stderr)
    sys.exit(2)


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, method=method, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "gameplatform-tunnel-setup/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_account():
    r = call("GET", "/accounts?per_page=50")
    accounts = r["result"]
    for a in accounts:
        zones = call("GET", "/zones?name=cree1p.com")
        if any(z["account"]["id"] == a["id"] for z in zones.get("result", [])):
            return a["id"]
    if accounts:
        return accounts[0]["id"]
    print("no account visible to this token", file=sys.stderr)
    sys.exit(1)


def find_zone(account_id):
    r = call("GET", "/zones?name=cree1p.com")
    for z in r["result"]:
        if z["account"]["id"] == account_id and z["name"] == "cree1p.com":
            return z["id"]
    print("zone cree1p.com not visible to this token", file=sys.stderr)
    sys.exit(1)


def main():
    account_id = find_account()
    print(f"account: {account_id}")
    zone_id = find_zone(account_id)
    print(f"zone:    {zone_id}")

    existing = call("GET", f"/accounts/{account_id}/cfd_tunnel?name={TUNNEL_NAME}")
    tunnels = [t for t in existing["result"] if t["name"] == TUNNEL_NAME]
    if tunnels:
        tunnel_id = tunnels[0]["id"]
        print(f"tunnel exists: {tunnel_id}")
    else:
        r = call("POST", f"/accounts/{account_id}/cfd_tunnel",
                 {"name": TUNNEL_NAME, "config_src": "cloudflare"})
        tunnel_id = r["result"]["id"]
        print(f"tunnel created: {tunnel_id}")

    r = call("GET", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/token")
    run_token = r["result"]
    out = os.path.expanduser(TOKEN_OUT)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(run_token)
    os.chmod(out, 0o600)
    print(f"run token written to {out} (mode 600)")

    dns_ok = True
    try:
        dns = call("GET", f"/zones/{zone_id}/dns_records?name={HOSTNAME}")
        if dns["result"]:
            print("dns record exists:", dns["result"][0]["id"])
        else:
            r = call("POST", f"/zones/{zone_id}/dns_records", {
                "type": "CNAME",
                "name": HOSTNAME,
                "content": f"{tunnel_id}.cfargotunnel.com",
                "proxied": True,
                "comment": "gameplatform (managed by deploy/create_tunnel.py)",
            })
            print("dns record created:", r["result"]["id"])
    except urllib.error.HTTPError as e:
        print(f"WARNING: DNS record not created (HTTP {e.code}, token lacks "
              f"Zone:DNS:Edit?). Add manually: CNAME {HOSTNAME} -> "
              f"{tunnel_id}.cfargotunnel.com (proxied)", file=sys.stderr)
        dns_ok = False

    cfg = {"ingress": [
        {"hostname": HOSTNAME, "service": SERVICE},
        {"service": "http_status:404"},
    ]}
    r = call("PUT", f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
             {"config": cfg})
    print("ingress set:", r.get("success"), "| version:", r.get("result", {}).get("version"))

    print(f"DONE. tunnel_id={tunnel_id} hostname={HOSTNAME} dns_ok={dns_ok}")
    print("next: docker compose -f deploy/docker-compose.yml --profile tunnel up -d")


if __name__ == "__main__":
    main()
