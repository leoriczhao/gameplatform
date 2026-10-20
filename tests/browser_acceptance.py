"""Real local browser against a running backend; use a disposable acceptance DB.

Creates a test account and one recorded match. No browser storage/tokens are saved.
Run: .venv/bin/python tests/browser_acceptance.py --base-url http://127.0.0.1:18089
Requires Playwright and its Chromium browser, or --cdp-url for a dedicated browser.
"""
import argparse
import json
from pathlib import Path
import secrets
import uuid

from playwright.sync_api import sync_playwright, expect


def run(base_url, output, cdp_url=None):
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = (playwright.chromium.connect_over_cdp(cdp_url) if cdp_url
                   else playwright.chromium.launch(headless=True))
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        page.set_default_timeout(15000)
        errors, replay_calls, replay_states, native_requests = [], [], [], []
        recording_replay = False
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: native_requests.append(request.url)
                if "/api/" in request.url and "/env/" in request.url else None)

        def websocket_seen(socket):
            if "/api/openenv/" not in socket.url or not socket.url.endswith("/ws"):
                return
            tracking = {"replay": False}

            def frame_sent(payload):
                frame = json.loads(payload)
                if recording_replay and frame.get("type") == "reset":
                    tracking["replay"] = True
                if tracking["replay"]:
                    call = {"url": socket.url, "direction": "sent",
                            "type": frame.get("type")}
                    if frame.get("type") == "reset":
                        call.update(frame.get("data") or {})
                    replay_calls.append(call)

            def frame_received(payload):
                if not tracking["replay"]:
                    return
                frame = json.loads(payload)
                replay_calls.append({"url": socket.url, "direction": "received",
                                     "type": frame.get("type")})
                if frame.get("type") == "error":
                    errors.append(f"OpenEnv replay error: {frame}")
                if frame.get("type") == "observation":
                    observation = frame["data"]["observation"]
                    if observation.get("state") is not None:
                        replay_states.append(observation["state"])

            socket.on("framesent", frame_sent)
            socket.on("framereceived", frame_received)

        page.on("websocket", websocket_seen)

        # 渲染 v2（16 §6）：主渲染路径是 canvas，DOM 只是回退；先等二者之一出现，
        # 再按实际渲染路径断言（避免首帧 canvas 尚未挂载时的竞态）。
        def expect_board(cells):
            page.wait_for_selector(
                'canvas, .grid[style*="grid-template-columns"] > button',
                state="visible", timeout=15000)
            if page.locator("canvas").count() == 0:
                expect(page.locator('.grid[style*="grid-template-columns"] > button')
                       ).to_have_count(cells)

        try:
            page.goto(base_url + "/")
            expect(page.get_by_text("后端在线", exact=False)).to_be_visible()
            for game in ("snake", "tetris", "microrts"):
                expect(page.locator(f'a[href="/games/{game}"]').first).to_be_visible()
            page.screenshot(path=str(output / "lobby.png"), full_page=True)

            page.get_by_role("button", name="登录 / 注册", exact=True).first.click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("tab", name="注册", exact=True).click()
            username = "browser_" + uuid.uuid4().hex[:10]
            dialog.get_by_label("用户名", exact=True).fill(username)
            dialog.get_by_label("密码", exact=True).fill(secrets.token_urlsafe(18))
            with page.expect_response(lambda r: r.url.endswith("/auth/register")) as registered:
                dialog.get_by_role("button", name="注册并登录", exact=True).click()
            assert registered.value.status == 200
            expect(dialog).not_to_be_visible()

            with page.expect_response(lambda r: r.url.endswith("/tetris/play/sessions")
                                      and r.request.method == "POST") as created:
                page.locator('a[href="/games/tetris"]').first.click()
            initial = created.value.json()["session"]
            expect_board(200)
            expect(page.get_by_text("分数", exact=False).first).to_be_visible()
            with page.expect_response(lambda r: "/tetris/play/sessions/" in r.url
                                      and r.url.endswith("/actions")) as stepped:
                page.keyboard.press("ArrowDown")
            transition = stepped.value.json()
            assert stepped.value.status == 200 and transition["state"]["tick"] > initial["state"]["tick"]
            page.screenshot(path=str(output / "tetris.png"), full_page=True)

            with page.expect_response(lambda r: r.url.endswith("/snake/play/sessions")
                                      and r.request.method == "POST") as snake:
                page.goto(base_url + "/games/snake")
            assert snake.value.status == 200
            expect_board(400)
            page.get_by_placeholder("动作（整数）").fill("1")
            for _ in range(30):
                with page.expect_response(lambda r: "/snake/play/sessions/" in r.url
                                          and r.url.endswith("/actions")) as move:
                    page.get_by_role("button", name="提交", exact=True).click()
                assert move.value.status == 200
                final = move.value.json()
                if final["done"]:
                    break
            else:
                raise AssertionError("snake did not reach a wall")
            expect(page.get_by_role("dialog")).to_be_visible()
            page.goto(base_url + "/records")
            replay_link = page.get_by_role("link", name="回放", exact=True).first
            expect(replay_link).to_be_visible()
            replay_path = replay_link.get_attribute("href")
            recording_replay = True
            with page.expect_response(lambda r: "/api/v1/matches/" in r.url
                                      and r.url.endswith("/replay")) as replay_response:
                replay_link.click()
            assert replay_response.value.status == 200
            replay_record = replay_response.value.json()["replay"]
            expect(page.get_by_text("回放控制", exact=True)).to_be_visible()
            expect(page.get_by_text("重建回放中…", exact=False)).not_to_be_visible(timeout=30000)
            assert replay_states and replay_states[-1] == final["state"]
            resets = [r for r in replay_calls if r["direction"] == "sent" and r["type"] == "reset"]
            assert resets and all(r.get("version") == replay_record["game_version"]
                                  and r.get("seed") == replay_record["seed"] for r in resets)
            steps = [r for r in replay_calls if r["direction"] == "sent" and r["type"] == "step"]
            assert len(steps) == len(replay_record["moves"])
            assert not any(r["type"] == "error" for r in replay_calls)
            recording_replay = False
            page.get_by_role("button", name="播放", exact=True).click()
            slider = page.get_by_role("slider")
            page.wait_for_function("Number(document.querySelector('[role=slider]').getAttribute('aria-valuenow')) > 0")
            pause = page.get_by_role("button", name="暂停", exact=True)
            if pause.is_visible():
                pause.click()
            slider.focus()
            page.keyboard.press("End")
            expect(slider).to_have_attribute("aria-valuenow", slider.get_attribute("aria-valuemax"))
            page.screenshot(path=str(output / "replay.png"), full_page=True)

            # 僵尸登录态回归（2026-09-08 线上事故）：gp_user 残留但 gp_token 已失效时，
            # 必须清掉残留并显示登录入口，而不是"看似已登录 + 空白棋盘 + unhandled 401"。
            page.evaluate(
                "() => { localStorage.removeItem('gp_token');"
                " localStorage.setItem('gp_user', JSON.stringify("
                "{id: 1, username: 'ghost', nickname: 'ghost'})); }")
            page.goto(base_url + "/games/snake")
            page.wait_for_timeout(1500)
            assert page.evaluate("() => localStorage.getItem('gp_user')") is None
            expect(page.get_by_role("button", name="登录 / 注册").first).to_be_visible()
            assert page.locator("canvas").count() >= 1, "游客应看到只读棋盘预览"
            assert not errors, errors
            assert not native_requests, native_requests
            result = {"base_url": base_url, "browser": browser.version,
                      "account_registration": "passed", "keyboard_gameplay": "passed",
                      "recorded_match": replay_path, "replay_matches_original": True,
                      "replay_playback_and_seek": "passed", "page_errors": errors,
                      "versioned_replay_requests": replay_calls,
                      "native_environment_requests": native_requests}
            (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({k: v for k, v in result.items() if k != "versioned_replay_requests"}, ensure_ascii=False))
        except Exception:
            page.screenshot(path=str(output / "failure.png"), full_page=True)
            print("Browser page errors:", errors)
            raise
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, default=Path("/tmp/gameplatform-browser-acceptance"))
    parser.add_argument("--cdp-url")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"), args.output, args.cdp_url)
