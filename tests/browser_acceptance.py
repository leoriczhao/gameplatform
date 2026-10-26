"""Real-browser smoke against a running backend (Lab UI).

Covers: home shell -> register/login -> single-player snake -> game over ->
matches list -> replay rebuild/playback -> models page -> PvP page shell ->
stale-login regression. Disposable account only; no browser storage saved.

Run (CI / local built app):
  python tests/browser_acceptance.py --base-url http://127.0.0.1:18080
Local against a dedicated browser (e.g. Edge CDP):
  python tests/browser_acceptance.py --base-url http://127.0.0.1:8080 \
      --cdp-url http://127.0.0.1:9222
Requires Playwright (chromium) unless --cdp-url is provided.
"""
import argparse
import json
import secrets
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def run(base_url, output, cdp_url=None):
    output.mkdir(parents=True, exist_ok=True)
    result = {"base_url": base_url, "steps": [], "page_errors": []}
    with sync_playwright() as playwright:
        browser = (playwright.chromium.connect_over_cdp(cdp_url) if cdp_url
                   else playwright.chromium.launch(headless=True))
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        page = context.new_page()
        page.set_default_timeout(20000)
        errors, native_requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: native_requests.append(request.url)
                if "/api/" in request.url and "/env/" in request.url else None)

        replay_calls, replay_states = [], []
        recording_replay = False

        def websocket_seen(socket):
            if "/api/openenv/" not in socket.url or not socket.url.endswith("/ws"):
                return
            tracking = {"replay": False}

            def frame_sent(payload):
                frame = json.loads(payload)
                if recording_replay and frame.get("type") == "reset":
                    tracking["replay"] = True
                if tracking["replay"]:
                    call = {"direction": "sent", "type": frame.get("type")}
                    if frame.get("type") == "reset":
                        call.update(frame.get("data") or {})
                    replay_calls.append(call)

            def frame_received(payload):
                if not tracking["replay"]:
                    return
                frame = json.loads(payload)
                replay_calls.append({"direction": "received", "type": frame.get("type")})
                if frame.get("type") == "error":
                    errors.append(f"OpenEnv replay error: {frame}")
                if frame.get("type") == "observation":
                    observation = frame["data"]["observation"]
                    if observation.get("state") is not None:
                        replay_states.append(observation["state"])

            socket.on("framesent", frame_sent)
            socket.on("framereceived", frame_received)

        page.on("websocket", websocket_seen)

        def step(name):
            result["steps"].append(name)
            return name

        def shot(name):
            page.screenshot(path=str(output / name), full_page=True)

        try:
            # 1. Home shell
            page.goto(base_url + "/")
            expect(page.get_by_text("API READY", exact=False).first).to_be_visible()
            expect(page.get_by_text("STREAM // RL LABORATORY", exact=False)).to_be_visible()
            expect(page.get_by_text("环境目录", exact=False).first).to_be_visible()
            shot("home.png")
            step("home")

            # 2. Register via Lab header dialog
            page.locator(".lab-header").get_by_role("button", name="登录", exact=True).click()
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            dialog.get_by_role("button", name="注册", exact=True).click()
            username = "browser_" + uuid.uuid4().hex[:10]
            password = secrets.token_urlsafe(14)
            dialog.locator('input[autocomplete="username"]').fill(username)
            dialog.locator('input[type="password"]').fill(password)
            with page.expect_response(lambda response: response.url.endswith("/api/v1/auth/register")) as registered:
                dialog.get_by_role("button", name="创建账号", exact=True).click()
            assert registered.value.status == 200, registered.value.text()
            expect(dialog).not_to_be_visible()
            expect(page.locator(".lab-header").get_by_text(username, exact=False).first).to_be_visible()
            shot("registered.png")
            step("register")

            # 3. Single-player snake: session is auto-created; integer controls
            with page.expect_response(
                lambda response: response.url.endswith("/api/v1/snake/play/sessions")
                and response.request.method == "POST",
            ) as created:
                page.goto(base_url + "/games/snake")
            assert created.value.status == 200, created.value.text()
            expect(page.locator(".lab-board-frame")).to_be_visible()
            action_input = page.locator(".play-action-input")
            expect(action_input).to_be_visible()
            final = None
            for _ in range(60):
                action_input.fill("1")
                with page.expect_response(
                    lambda response: "/api/v1/snake/play/sessions/" in response.url
                    and response.url.endswith("/actions"),
                ) as stepped:
                    page.get_by_role("button", name="提交动作", exact=True).click()
                assert stepped.value.status == 200, stepped.value.text()
                final = stepped.value.json()
                if final.get("done"):
                    break
            assert final and final.get("done"), "snake did not finish"
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_text("FINAL SCORE", exact=False)).to_be_visible()
            shot("snake-game-over.png")
            step("single-player")

            # 4. Matches list
            page.goto(base_url + "/matches")
            expect(page.get_by_role("heading", name="对局与回放", exact=False)).to_be_visible()
            expect(page.get_by_text("MATCHES", exact=False).first).to_be_visible()
            shot("matches.png")
            step("matches")

            # 5. Replay page (rebuild via OpenEnv WS, play, seek)
            token = page.evaluate("() => localStorage.getItem('gp_token')")
            headers = {"Authorization": f"Bearer {token}"}
            matches = page.request.get(base_url + "/api/v1/matches", headers=headers).json()["matches"]
            match = next(item for item in matches if item["game"] == "snake" and item["kind"] == "pve")
            replay = page.request.get(
                base_url + f"/api/v1/matches/{match['id']}/replay").json()["replay"]
            assert replay["moves"], "recorded snake match has no moves"
            recording_replay = True
            with page.expect_response(
                lambda response: response.url.endswith(f"/api/v1/matches/{match['id']}/replay"),
            ) as replay_response:
                page.goto(base_url + f"/watch/match/{match['id']}")
            assert replay_response.value.status == 200
            expect(page.get_by_text("回放控制", exact=True)).to_be_visible()
            expect(page.get_by_text("重建回放中", exact=False)).not_to_be_visible(timeout=30000)
            slider = page.get_by_role("slider")
            expect(slider).to_be_visible()
            expect(slider).to_be_enabled()
            page.get_by_role("button", name="播放", exact=True).click()
            page.wait_for_function(
                "() => Number(document.querySelector('input[aria-label=\"回放进度\"]').value) > 0")
            pause = page.get_by_role("button", name="暂停", exact=True)
            if pause.is_visible():
                pause.click()
            slider.focus()
            page.keyboard.press("End")
            expect(slider).to_have_value(slider.get_attribute("max"))
            assert replay_states and replay_states[-1] == final["state"], "rebuilt final state mismatch"
            resets = [call for call in replay_calls
                      if call["direction"] == "sent" and call["type"] == "reset"]
            assert resets and all(
                call.get("version") == replay.get("game_version") and call.get("seed") == replay.get("seed")
                for call in resets), resets
            steps = [call for call in replay_calls
                     if call["direction"] == "sent" and call["type"] == "step"]
            assert len(steps) == len(replay["moves"]), (len(steps), len(replay["moves"]))
            assert not any(call["type"] == "error" for call in replay_calls)
            recording_replay = False
            shot("replay.png")
            step("replay")

            # 6. Models shell
            page.goto(base_url + "/models")
            expect(page.get_by_role("heading", name="模型", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="上传 ONNX", exact=False)).to_be_visible()
            shot("models.png")
            step("models")

            # 7. PvP shell (no second account; just verify the find-opponent surface)
            page.goto(base_url + "/games/microrts/pvp")
            expect(page.get_by_text("找对手", exact=False).first).to_be_visible()
            expect(page.get_by_text("PUBLIC ROOMS", exact=False)).to_be_visible()
            shot("pvp.png")
            step("pvp-shell")

            # 8. Stale-login regression: gp_user without gp_token must be cleared
            page.evaluate(
                "() => { localStorage.removeItem('gp_token');"
                " localStorage.setItem('gp_user', JSON.stringify("
                "{id: 1, username: 'ghost', nickname: 'ghost'})); }")
            page.goto(base_url + "/games/snake")
            page.wait_for_timeout(1500)
            assert page.evaluate("() => localStorage.getItem('gp_user')") is None
            expect(page.locator(".lab-header").get_by_role("button", name="登录", exact=True)).to_be_visible()
            expect(page.locator(".lab-board-frame")).to_be_visible()
            shot("guest-preview.png")
            step("stale-login")

            assert not errors, errors
            assert not native_requests, native_requests
            result.update({
                "browser": browser.version,
                "account": username,
                "match_id": match["id"],
                "replay_moves": len(replay["moves"]),
                "page_errors": errors,
                "native_environment_requests": native_requests,
            })
            (output / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({key: value for key, value in result.items()
                              if key not in ("steps",)}, ensure_ascii=False))
            print("steps:", ", ".join(result["steps"]))
        except Exception:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            print("Browser page errors:", errors)
            print("Steps completed:", result["steps"])
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path,
                        default=Path("/tmp/gameplatform-browser-acceptance"))
    parser.add_argument("--cdp-url")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"), args.output, args.cdp_url)
