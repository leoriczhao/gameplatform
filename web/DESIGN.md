# Stream Web 设计规范(shadcn/ui + Tailwind · 亮色极简风)

迁移目标:所有页面从 antd 重写为 shadcn/ui + Tailwind,**业务逻辑与 API 调用保持不变**。

## 1. 硬性规则

- **禁止** `import ... from "antd"` / `"@ant-design/icons"`。图标一律用 `lucide-react`。
- 路由、hooks、api.js 调用、AuthContext 用法**完全保持原逻辑**。
- toast:`import { toast } from "sonner"` → `toast.success/error/info`。
- 页面不再自带 header 和登录弹窗:全局 header 在 `components/AppShell.jsx`;
  登录按钮 → `const openLogin = useLogin();`(来自 `../components/LoginProvider.jsx`)。
- 每个页面根节点:`<div className="page-shell">`。
- 页面标题区用 `<PageHeader icon={...} title="..." description="..." actions={...} />`。
- 装饰性 emoji 换 lucide 图标;数据内容里的 emoji 保留。

## 2. 组件清单(src/components/ui/*)

> 清单 = 已实现且有引用的组件；新页面需要新组件时按 shadcn 惯例新增。

- `button.jsx` — `<Button variant="default|destructive|outline|secondary|ghost|link" size="default|sm|lg|icon|icon-sm" asChild>`。
- `card.jsx` — Card/CardHeader/CardTitle/CardDescription/CardContent/CardFooter。可交互卡片加 `hover-lift`。
- `badge.jsx` — `<Badge variant="default|secondary|destructive|success|warning|info|outline">`。
- `input/textarea/label` — 受控表单,错误显示 `<p className="text-sm text-red-600">`。
- `checkbox/radio-group` — `checked + onCheckedChange` / `value + onValueChange`。
- `select.jsx` — Select/SelectTrigger/SelectValue/SelectContent/SelectItem(Radix,value 必须字符串)。
- `tabs.jsx`、`dialog.jsx`、`confirm.jsx`(替代 Popconfirm)、`dropdown-menu.jsx`、`avatar.jsx`、`tooltip.jsx`、
  `progress.jsx`、`slider.jsx`、`table.jsx`、`alert.jsx`(variant default/info/success/warning/destructive)、
  `spinner.jsx`、`empty-state.jsx`、`stat.jsx`、`page-header.jsx`、
  `pagination.jsx`(`usePaged(rows, pageSize)` + `<Pagination/>`)。
- 布局:antd Row/Col/Space → Tailwind flex/grid + gap。

## 3. 视觉风格(亮色极简)

- **底色**:`#fafafa` 极浅灰,卡片纯白 `shadow-sm` + 1px `#e4e4e7` 边框。
- **文字**:近黑墨色 `#19191c`,次级 `text-muted-foreground`。
- **强调色**:靛蓝 `#4f46e5`,只用于主按钮、链接、激活态、焦点环、进度条。
- **禁用**:光晕阴影(glow)、彩色渐变文字/背景、彩色徽章滥用。
  状态徽章只按语义用色(成功=emerald、警告=amber、危险=red、信息=sky),其余一律中性灰。
- 标题用 `gradient-text` class(现为纯墨色,保留 class 兼容)。
- 游戏画布:浅色板(Snake/Tetris `#f8fafc`,Microrts 棋盘 `#f4f4f5/#ebebee`),
  放 `.board-shell` 白色容器内。
- 移动端:grid 用 `grid-cols-1 md:grid-cols-2` 响应式。

## 4. 共享组件

- `components/AppShell.jsx` — 全局 header。
- `components/LoginProvider.jsx` — `useLogin()`。
- `components/LevelBadge.jsx` — 等级徽章。
- `components/UgBoard.jsx` — 通用棋盘门面（props 不变：state/meta/onCellClick/cellSize）；
  `src/render/` — 渲染 v2 实现（schema 归一化/动效/资源/Canvas/DOM/HUD/沙箱宿主，见 docs/design/16）。
- `api.js`、`AuthContext.jsx` — 不变。

## 5. 完成检查

- grep 无 `antd`、`@ant-design/icons`、`styles.css`。
- API 调用、轮询间隔、localStorage key、URL 参数与原文一致。
- 文件 UTF-8。
