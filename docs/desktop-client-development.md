# SenaBot Desktop 客户端开发文档

> 状态：首版开发基线  
> 目标平台：Windows 优先  
> 技术方案：Electron + React + TypeScript + Python 核心进程  
> 当前阶段：先完成可在 Electron 开发窗口运行、连接现有 Desktop Adapter 的客户端 UI；Python 自动启动与打包随后接入。

## 1. 产品目标

SenaBot Desktop 是一个本地单用户角色陪伴客户端。页面的唯一核心任务是让角色保持“在场”，并让用户自然完成一轮文本对话。

客户端不是传统聊天软件，不使用消息气泡瀑布流。角色立绘是主视觉，当前回复和输入区域组成视觉小说式对白界面。

首版必须具备：

- Electron 桌面窗口中的完整 React UI；
- 上方角色舞台、下方对白框；
- 左上角设置按钮和设置抽屉；
- 连接现有 `ws://127.0.0.1:8765` Desktop Adapter；
- 发送文本、接收文本、等待回复、断线重连和连接占用状态；
- 设置持久化；
- 键盘操作、可见焦点和减少动态效果支持；
- 从本地未入库的角色资源目录加载透明立绘。

首版不做：

- 完整聊天历史与持久化；
- Live2D；
- 图片、音频或文件消息；
- 多用户、多窗口连接路由；
- Agent/Context 实现；
- Python 后端安装包和自动更新。

## 2. 已有后端边界

现有组合根位于 `src/main.py`，启动后监听：

```text
ws://127.0.0.1:8765
```

浏览器或 Electron Renderer 发给 Adapter：

```json
{
  "type": "message",
  "message_id": "由客户端生成的 UUID",
  "text": "用户输入"
}
```

Adapter 发给客户端：

```json
{
  "type": "message",
  "text": "角色回复",
  "reply_to": "被回复的 message_id 或 null"
}
```

约束：

- 客户端不提交可信身份；owner 身份由 `DesktopAdapter` 注入；
- Desktop Connector 同时只允许一个 active connection；
- 第二个连接会以 WebSocket close code `1013` 关闭；
- `1013` 表示连接被占用，客户端不得无限自动重连；
- 当前 `main.py` 没有 Agent/Context 消费者，因此能接收入站消息但不会自行产生回复；
- 前端不得伪造服务端回复。联调回声应由独立开发代码提供，且不得污染 Adapter/Body 边界。

## 3. 应用架构

```text
SenaBot Desktop
├── Electron main process
│   ├── desktop window
│   └── future: launch/monitor Python core process
├── React UI
│   ├── character stage
│   ├── dialogue panel
│   ├── settings drawer
│   └── connection state
└── Python core
    ├── EventBus
    ├── BodyRuntime
    └── DesktopAdapter / WebSocketConnector
```

开发阶段分别启动 Python 和 Electron。发布阶段再将 Python 打包成 `senabot-core.exe`，由 Electron 主进程启动和监控。

## 4. 技术栈

| 领域 | 选择 |
|---|---|
| 桌面外壳 | Electron |
| UI | React |
| 语言 | TypeScript |
| 构建 | Vite |
| 样式 | 全局 CSS + CSS variables |
| 通信 | 浏览器原生 WebSocket |
| 状态 | React 局部 hooks |
| 设置存储 | `localStorage` |
| 单元测试 | Vitest + Testing Library |
| E2E（后续） | Playwright |

首版不引入 Tailwind、Ant Design、Material UI、Redux 或 Zustand。当前状态规模不需要这些依赖，定制界面也不应被通用组件视觉限制。

## 5. 视觉设计基线

### 5.1 主题

设计主题为“纯白角色舞台”。界面只使用黑、白、灰建立层级，角色立绘是唯一彩色内容；避免渐变、霓虹描边、玻璃卡片和聊天气泡。

### 5.2 标志性元素

唯一的视觉冒险是“角色侵入对白框”：立绘主体在对白框后方，局部前景可越过对白框边缘。即使首版只有单张图片，也要通过遮挡和层级让角色看起来站在对白界面旁，而不是把 PNG 放在独立图片区。

图层顺序：

```text
背景             z-index: 0
角色主体         z-index: 10
对白框           z-index: 20
角色前景（可选） z-index: 30
设置与提示       z-index: 40
```

### 5.3 色彩 token

| token | 色值 | 用途 |
|---|---:|---|
| `--color-stage` | `#ffffff` | 舞台背景 |
| `--color-panel` | `rgba(255,255,255,.97)` | 对白框实体 |
| `--color-text` | `#171717` | 主文本 |
| `--color-accent` | `#171717` | 角色名、焦点、主要操作 |
| `--color-online` | `#4f755c` | 在线状态 |
| `--color-muted` | `#737373` | 辅助信息 |

### 5.4 字体

- 角色名：`"LXGW WenKai", "Noto Serif SC", serif`；
- 对话和输入：`"Noto Sans SC", "Microsoft YaHei", sans-serif`；
- 状态与技术信息：`"IBM Plex Mono", "Cascadia Mono", monospace`。

不依赖在线字体，保证离线启动。

### 5.5 布局

```text
┌──────────────────────────────────────┐
│ 设置                           在线  │
│                                      │
│              角色立绘                │
│            （进入对白框）            │
│  ┌────────────────────────────────┐  │
│  │ SENA                           │  │
│  │ “今天想聊些什么？”             │  │
│  │ 你刚才说：……                   │  │
│  │ [和她说点什么……            →] │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

桌面布局参数：

- 舞台约占窗口高度 `68%`；
- 对白区域约占 `32%`；
- 对白框最大宽度 `920px`；
- 内容外边距不小于 `24px`；
- 立绘以放大的上半身构图为主，下半身由对白框自然遮挡；
- 窗口高度不足时优先保证回复和输入可操作，再缩小立绘。

## 6. 交互和状态

连接状态：

```ts
type ConnectionStatus =
  | "connecting"
  | "connected"
  | "waiting"
  | "reconnecting"
  | "disconnected"
  | "occupied";
```

| 状态 | 用户界面 |
|---|---|
| `connecting` | “正在连接本地服务”，输入暂时禁用 |
| `connected` | 青色状态点和“在线”，允许发送 |
| `waiting` | “Sena 正在回应”，保留上一条用户消息 |
| `reconnecting` | “连接已断开，正在重连”，保留草稿 |
| `disconnected` | 显示“重新连接”操作 |
| `occupied` | “另一个 Desktop 页面正在使用连接”，停止自动重连 |

输入规则：

- `Enter` 发送；
- `Shift + Enter` 换行；
- 空白文本不可发送；
- 未连接时不可发送；
- 发送后清空输入框，保存上一条用户消息；
- 使用 `crypto.randomUUID()` 生成 `message_id`；
- 收到消息时展示 `text`，并结束等待状态；
- 服务端消息必须在运行时校验，未知消息不能破坏 UI。

错误文案必须说明状态和下一步，例如“无法连接本地服务。请确认 SenaBot 核心已启动”，不能只显示“发生错误”。

## 7. 设置

设置抽屉从左侧打开，至少包含：

```ts
interface DesktopSettings {
  socketUrl: string;
  characterName: string;
  textSpeed: number;
  autoReconnect: boolean;
  sendWithEnter: boolean;
}
```

默认值：

```ts
{
  socketUrl: "ws://127.0.0.1:8765",
  characterName: "Sena",
  textSpeed: 28,
  autoReconnect: true,
  sendWithEnter: true
}
```

要求：

- 使用明确的“保存更改”按钮；
- 保存到 `localStorage`；
- 修改服务地址后，保存时重建连接；
- Escape 关闭抽屉；
- 抽屉打开后管理焦点，按钮必须有可见焦点态。

## 8. 动效与无障碍

主要入场动效只执行一次：背景 → 角色轻微上移 → 对白框出现 → 开场文字淡入。

角色不使用循环呼吸动画。禁止散布无意义的漂浮光点、循环渐变和多个持续闪烁元素。

必须支持：

- `prefers-reduced-motion: reduce`；
- 键盘完整操作；
- `:focus-visible`；
- 图标按钮的 `aria-label`；
- 状态变化使用适当的 `aria-live`，但避免逐字动画每个字符都播报；
- 文本与背景达到可读对比度。

## 9. 推荐目录

```text
frontend/
├── electron/
│   └── main.cjs
├── public/
│   └── characters/
├── src/
│   ├── components/
│   │   ├── CharacterStage/
│   │   ├── DialoguePanel/
│   │   ├── MessageComposer/
│   │   ├── SettingsDrawer/
│   │   └── ConnectionIndicator/
│   ├── services/
│   │   └── desktopSocket.ts
│   ├── state/
│   ├── styles/
│   │   ├── tokens.css
│   │   ├── global.css
│   │   └── motion.css
│   ├── types/
│   │   └── protocol.ts
│   ├── App.tsx
│   └── main.tsx
├── package.json
├── tsconfig.json
└── vite.config.ts
```

## 10. 首版实施阶段

### Phase 1：工程与协议

- 初始化 Vite React TypeScript；
- 初始化 Electron 主进程与开发启动脚本；
- 实现协议类型和运行时校验；
- 实现 WebSocket 连接、关闭、重连和 `1013` 处理；
- 为协议和 WebSocket 状态编写单元测试。

### Phase 2：核心界面

- 实现角色舞台；
- 实现角色侵入对白框的图层；
- 实现当前回复、上一条用户消息和输入；
- 实现全部连接状态；
- 从本地角色资源目录加载可替换的透明立绘；美术文件不进入 Git。

### Phase 3：设置与体验

- 实现设置抽屉；
- `localStorage` 持久化；
- 修改服务地址后重连；
- 添加 reduced motion、焦点和响应式处理；
- 完成组件测试和构建验证。

### Phase 4：Python 核心进程（后续）

- 将 Python 核心打包为独立可执行文件；
- Electron 启动、监控和关闭 Python 核心进程；
- 动态端口或启动令牌；
- 应用单实例和系统托盘；
- Windows 安装包。

## 11. 首版验收标准

- `frontend` 可以安装依赖并通过生产构建；
- Electron 主进程存在，并可通过 `npm.cmd run electron:dev` 启动开发窗口；
- 在 `ws://127.0.0.1:8765` 可连接时，状态变为“在线”；
- 用户可以发送符合现有 `DesktopCodec` 的 JSON；
- 合法服务端消息会显示为角色当前回复；
- 服务关闭后自动重连，草稿不丢失；
- close code `1013` 显示连接占用，并停止自动重连；
- 设置可保存并在刷新后恢复；
- 页面在常见桌面窗口和窄窗口下保持可操作；
- 键盘焦点清楚，减少动态效果有效；
- 界面没有聊天气泡流、通用后台卡片或模板化霓虹渐变；
- 自动化测试和现有 Python 测试均不因本次开发受损。

## 12. 后续决策

首版完成后再决定：

1. Python 核心使用何种打包方案；
2. Electron 与 Python 核心的启动令牌和动态端口协议；
3. Agent/Context 接入后的流式回复协议；
4. 角色资源包格式与 Live2D 适配层；
5. 对话历史由 Memory 还是独立会话读取接口提供。
