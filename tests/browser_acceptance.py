"""Real-browser smoke against a running backend (Lab UI, design 17 M3 stage).

Covers: home shell -> register/login -> /games/:slug setup -> POST /api/v2/matches
-> /m/:id stage (SSE tick, resign, result card, frame review) -> /matches rows ->
Environment play tab embedding the stage -> timeline event marks -> models page ->
PvP lobby -> stale-login regression. Disposable account only; no browser storage
saved.

Run (CI / local built app):
  python tests/browser_acceptance.py --base-url http://127.0.0.1:18080
Local against a dedicated browser (e.g. Edge CDP):
  python tests/browser_acceptance.py --base-url http://127.0.0.1:8080 \
      --cdp-url http://127.0.0.1:9222
Requires Playwright (chromium) unless --cdp-url is provided.
"""
import argparse
import json
import re
import secrets
import uuid
from collections import deque
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

STREAM_RE = re.compile(r"/api/v2/matches/[^/]+/stream$")


def run(base_url, output, cdp_url=None):
    output.mkdir(parents=True, exist_ok=True)
    result = {"base_url": base_url, "steps": [], "page_errors": []}
    with sync_playwright() as playwright:
        browser = (playwright.chromium.connect_over_cdp(cdp_url) if cdp_url
                   else playwright.chromium.launch(headless=True))
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
        # 本机/CI 可能没有外网：Google Fonts 请求挂起会拖住 load 事件，直接 abort。
        context.route(re.compile(r"https://fonts\.(googleapis|gstatic)\.com/.*"),
                      lambda route: route.abort())
        page = context.new_page()
        page.set_default_timeout(20000)
        errors, native_requests, stream_requests = [], [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        # 认输等危险操作会 window.confirm，Playwright 默认自动取消，这里统一放行。
        page.on("dialog", lambda dialog: dialog.accept())
        page.on("request", lambda request: native_requests.append(request.url)
                if "/api/" in request.url and "/env/" in request.url else None)
        page.on("request", lambda request: stream_requests.append(request.url)
                if STREAM_RE.search(request.url) else None)

        def step(name):
            result["steps"].append(name)
            return name

        def shot(name):
            page.screenshot(path=str(output / name), full_page=True)

        def api_headers():
            token = page.evaluate("() => localStorage.getItem('gp_token')")
            return {"Authorization": f"Bearer {token}"}

        def api_get(path):
            response = page.request.get(base_url + path, headers=api_headers())
            assert response.ok, (path, response.status, response.text())
            return response.json()

        def api_post(path, payload, status=201):
            response = page.request.post(
                base_url + path,
                headers={**api_headers(), "Content-Type": "application/json"},
                data=json.dumps(payload),
            )
            assert response.status == status, (path, response.status, response.text())
            return response.json()

        # 单座 snake 练习局：用 BFS 把蛇开到食物，拿到一个确定的 eat 事件刻度。
        DIR_VEC = {0: (0, -1), 1: (0, 1), 2: (-1, 0), 3: (1, 0)}
        CLOCKWISE = {0: 3, 3: 1, 1: 2, 2: 0}   # up -> right -> down -> left

        def snake_toward_food(state):
            body = [tuple(cell) for cell in state["body"]]
            head, food = body[0], tuple(state["food"])
            width, height = state.get("grid", [20, 20])[:2]
            blocked = set(body[:-1])          # the tail vacates this tick
            prev = {head: None}
            queue = deque([head])
            while queue:
                cell = queue.popleft()
                if cell == food:
                    break
                for dx, dy in DIR_VEC.values():
                    nxt = (cell[0] + dx, cell[1] + dy)
                    if not (0 <= nxt[0] < width and 0 <= nxt[1] < height):
                        continue
                    if nxt in blocked or nxt in prev:
                        continue
                    prev[nxt] = cell
                    queue.append(nxt)
            if food not in prev:
                return None                   # boxed in: start a fresh practice match
            cell = food
            while prev[cell] != head:
                cell = prev[cell]
            direction = next(key for key, vec in DIR_VEC.items()
                             if (head[0] + vec[0], head[1] + vec[1]) == cell)
            current = state["direction"]
            if direction == current:
                return 1
            return 2 if CLOCKWISE[current] == direction else 0

        def drive_snake_to_food():
            match_id = api_post("/api/v2/matches", {
                "game": "snake",
                "seats": [{"seat": "p0", "occupant": "me",
                           "controller": {"type": "human"}}],
                "mode": "practice", "visibility": "unlisted",
            })["id"]
            for _ in range(60):
                view = api_get(f"/api/v2/matches/{match_id}")
                if "eat" in (view.get("events") or []) or view["frame"].get("score", 0) > 0:
                    break
                action = snake_toward_food(view["frame"])
                assert action is not None, view["frame"]
                api_post(f"/api/v2/matches/{match_id}/actions",
                         {"tick": view["tick"], "action": action}, status=202)
                page.wait_for_timeout(40)
            else:
                raise AssertionError("snake never ate food")
            frames = api_get(f"/api/v2/matches/{match_id}/frames?from=0&limit=500")["frames"]
            eat_tick = next(frame["tick"] for frame in frames
                            if "eat" in (frame.get("events") or []))
            return match_id, eat_tick

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

            # 3. Single-player setup page -> v2 match -> /m/:id stage
            page.goto(base_url + "/games/snake")
            expect(page.locator(".lab-h1").first).to_be_visible()
            start = page.get_by_role("button", name="开始对局", exact=True)
            expect(start).to_be_visible()
            with page.expect_response(
                lambda response: response.url.endswith("/api/v2/matches")
                and response.request.method == "POST",
            ) as created:
                start.click()
            assert created.value.status == 201, created.value.text()
            match = created.value.json()
            match_id = match["id"]
            assert match["status"] == "active" and match["you"]["seat"] == "p0", match
            expect(page).to_have_url(re.compile(r"/m/[^/?#]+"))
            expect(page.locator(".stage")).to_be_visible()
            expect(page.locator(".stage-clock__value")).to_have_text("0")
            shot("stage-live.png")
            step("stage-create")

            # 4. Play one tick with the keyboard: SSE pushes the tick to the stage
            page.keyboard.press("ArrowRight")
            expect(page.locator(".stage-clock__value")).to_have_text("1")
            view = page.request.get(base_url + f"/api/v2/matches/{match_id}",
                                    headers=api_headers()).json()
            assert view["tick"] == 1, view
            assert stream_requests, "stage did not open the result stream"
            step("stage-tick")

            # 5. Resign -> result card from the stream -> frame review -> Esc
            page.get_by_role("button", name="认输", exact=True).click()
            result_card = page.locator(".stage-card--result")
            expect(result_card).to_be_visible()
            expect(result_card.locator(".stage-card__title")).to_be_visible()
            shot("stage-result.png")
            step("stage-result")

            review = page.get_by_role("button", name="回看本局", exact=True)
            expect(review).to_be_visible()
            review.click()
            banner = page.locator(".stage-banner--review")
            expect(banner).to_be_visible()
            expect(banner).to_contain_text("回看中")
            shot("stage-review.png")
            page.keyboard.press("Escape")
            expect(banner).to_have_count(0)
            step("stage-review")

            # 6. Matches list links rows to /m/:uid
            page.goto(base_url + "/matches")
            expect(page.get_by_role("heading", name="对局记录", exact=False)).to_be_visible()
            row = page.locator("a.mat-row").first
            expect(row).to_be_visible()
            href = row.get_attribute("href")
            assert href and href.startswith("/m/"), href
            shot("matches.png")
            step("matches")

            # 7. Reopen the finished match: the stage restores the result from the record
            page.goto(base_url + href)
            expect(page.locator(".stage-card--result")).to_be_visible()
            expect(page.locator(".stage-clock__label").first).to_have_text("FINAL")
            step("stage-record")

            # 8. Environment play tab: create a practice match and embed the stage
            page.goto(base_url + "/environments/snake")
            expect(page.locator(".lab-h1").first).to_be_visible()
            page.get_by_role("tab", name="试玩", exact=True).click()
            intro = page.locator(".envp-stage__intro")
            expect(intro.get_by_text("PLAYGROUND · V2 STAGE", exact=False)).to_be_visible()
            with page.expect_response(
                lambda response: response.url.endswith("/api/v2/matches")
                and response.request.method == "POST",
            ) as env_created:
                intro.get_by_role("button", name="开始试玩", exact=True).click()
            assert env_created.value.status == 201, env_created.value.text()
            env_match = env_created.value.json()
            env_match_id = env_match["id"]
            assert env_match["mode"] == "practice" and env_match["visibility"] == "unlisted", env_match
            assert len(env_match["seats"]) == 1, env_match
            embed = page.locator(".envp-stage__embed")
            expect(embed.locator(".stage")).to_be_visible()
            expect(embed.locator(".stage-timeline")).to_be_visible()
            expect(embed.locator(".stage-clock__value")).to_have_text("0")
            shot("environment-play.png")
            # Switching tabs keeps the same live match (stage reconnects by snapshot)
            page.get_by_role("tab", name="概览", exact=True).click()
            page.get_by_role("tab", name="试玩", exact=True).click()
            expect(page.locator(".envp-stage__id")).to_contain_text(env_match_id[:8])
            page.get_by_role("button", name="换一局", exact=True).click()
            expect(page.get_by_text("PLAYGROUND · V2 STAGE", exact=False)).to_be_visible()
            step("environment-play")

            # 9. Timeline event marks: a real eat event shows up as a clickable dot
            snake_id, eat_tick = drive_snake_to_food()
            page.goto(base_url + f"/m/{snake_id}")
            expect(page.locator(".stage")).to_be_visible()
            marks = page.locator(".stage-timeline__mark")
            expect(marks.first).to_be_visible()
            assert marks.count() >= 1, marks.count()
            good_mark = page.locator(".stage-timeline__mark--good").first
            expect(good_mark).to_have_attribute("title", re.compile("吃到食物"))
            good_mark.click()
            review_banner = page.locator(".stage-banner--review")
            expect(review_banner).to_be_visible()
            expect(review_banner).to_contain_text("回看中")
            expect(page.locator(".stage-timeline__live")).to_contain_text("REVIEW")
            shot("timeline-events.png")
            page.keyboard.press("Escape")
            expect(review_banner).to_have_count(0)
            api_post(f"/api/v2/matches/{snake_id}/resign", {}, status=200)
            step("timeline-events")

            # 10. Models shell
            page.goto(base_url + "/models")
            expect(page.get_by_role("heading", name="模型", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="上传 ONNX", exact=False)).to_be_visible()
            shot("models.png")
            step("models")

            # 11. PvP lobby (no second account; just verify the v2 surfaces)
            page.goto(base_url + "/games/microrts/pvp")
            expect(page.locator(".lab-h1").first).to_contain_text("对战大厅")
            expect(page.get_by_text("创建房间", exact=False).first).to_be_visible()
            expect(page.get_by_text("快速匹配", exact=False).first).to_be_visible()
            shot("pvp.png")
            step("pvp-lobby")

            # 12. Stale-login regression: gp_user without gp_token must be cleared
            page.evaluate(
                "() => { localStorage.removeItem('gp_token');"
                " localStorage.setItem('gp_user', JSON.stringify("
                "{id: 1, username: 'ghost', nickname: 'ghost'})); }")
            page.goto(base_url + "/games/snake")
            page.wait_for_timeout(1500)
            assert page.evaluate("() => localStorage.getItem('gp_user')") is None
            expect(page.locator(".lab-header").get_by_role("button", name="登录", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="开始对局", exact=True)).to_be_visible()
            shot("guest-setup.png")
            step("stale-login")

            assert not errors, errors
            assert not native_requests, native_requests
            result.update({
                "browser": browser.version,
                "account": username,
                "match_id": match_id,
                "page_errors": errors,
                "native_environment_requests": native_requests,
                "stream_requests": len(stream_requests),
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
