/* M4 契约：聊天改走对局 SSE，不再 REST 轮询。
   useMatch 是 React hook、SidePanel 是组件，本仓测试环境没有 DOM 渲染器，
   所以这里用源码级断言守住"不再 GET /chat"这条契约；消息归并行为由
   stage-reduce.test.js 里 reduceMatch 的纯函数测试覆盖。 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => readFileSync(join(ROOT, relative), "utf8");

test("useMatch no longer polls the retired chat endpoint", () => {
  const source = read("src/stage/useMatch.js");
  assert.ok(!source.includes("CHAT_POLL_MS"), "CHAT_POLL_MS 应已删除");
  assert.ok(!source.includes("chatSince"), "chatSince 游标应已删除");
  assert.ok(!source.includes("/chat?since"), "不应再请求 GET /chat?since");
  assert.doesNotMatch(source, /getJson\([^)]*\/chat/, "聊天不能再用 getJson 拉取");
});

test("sendChat posts once and folds the returned message into the reducer", () => {
  const source = read("src/stage/useMatch.js");
  assert.ok(source.includes("matches/${uid}/chat"));
  assert.ok(source.includes("{ text }"), "POST body 仍是 { text }");
  assert.ok(source.includes('type: "chat"'), "POST 返回的消息要走 chat reducer 事件");
  assert.ok(source.includes("reduceMatch(current"), "乐观追加经过 reduceMatch");
  assert.ok(!source.includes("setChat"), "不再单独维护 chat state");
});

test("Stage no longer passes a chat prop; SidePanel reads it from the view", () => {
  const stage = read("src/stage/Stage.jsx");
  assert.ok(stage.includes("<SidePanel view={view}"), "SidePanel 仍挂在舞台上");
  const signature = read("src/stage/slots/SidePanel.jsx")
    .split("\n").find((line) => line.startsWith("export default function SidePanel"));
  assert.ok(signature, "SidePanel 签名存在");
  assert.ok(!/\bchat\b/.test(signature), "SidePanel 不再接收 chat prop");
  const sidePanel = read("src/stage/slots/SidePanel.jsx");
  assert.ok(sidePanel.includes("view?.chat"), "聊天从 view.chat 派生");
  assert.ok(!sidePanel.includes("getJson"), "侧栏不再自己拉聊天");
});
