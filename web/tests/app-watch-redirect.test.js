/* M4：旧 /watch/match/:id 直达舞台（v1 历史详情 → uid → /m/:uid）。
   App.jsx 是路由组件，本仓没有 DOM 测试环境；这里用源码级断言守住路由契约，
   实际跳转在浏览器验收覆盖（v1 详情返回 match.uid 时跳 /m/:uid，否则 /matches）。 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (relative) => readFileSync(join(ROOT, relative), "utf8");

test("legacy /watch/match/:id redirects through the v1 match detail API", () => {
  const app = read("src/App.jsx");
  assert.ok(app.includes("function LegacyMatchRedirect"), "映射组件存在");
  assert.ok(app.includes("api/v1/matches/"), "读取 v1 历史详情");
  assert.ok(app.includes("match?.uid"), "从 v1 记录取 uid");
  assert.ok(app.includes("navigate(uid ?"), "有 uid 才跳舞台");
  assert.ok(app.includes('"/matches"'), "无 uid 回对局列表");
  assert.ok(app.includes("replace: true"), "用 replace 不留历史栈");
  assert.ok(app.includes('path="/watch/match/:matchId"'), "旧对局链接走映射组件");
  assert.ok(app.includes("<LegacyMatchRedirect />"), "路由 element 已替换");
  assert.ok(app.includes('path="/watch/:game/:sessionId"'), "更老的会话回放路由仍在");
  assert.ok(!app.includes('path="/watch/match/:matchId" element={<Navigate'), "不再直接 Navigate 到列表");
});
