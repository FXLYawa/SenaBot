# SenaBot Desktop

## 日常启动（Windows 源码版）

双击仓库根目录的 `StartSenaBot.cmd`。首次运行会安装前端依赖，之后构建并打开桌面窗口。
需要已安装 Node.js，并已创建项目 `.venv`、安装 `requirements.txt` 中的 Python 依赖。

首次打开会显示设置页，只需填写两个 API Key：

- 对话模型 API Key。
- 硅基流动 API Key，供 Embedding 和 Reranker 共用。

点击“保存密钥并重启后端”。模型、服务地址、超时等继续使用仓库 `config/*.toml`，界面不提供修改。
显示“后端已启动”只代表本地服务可用；发一条消息才能验证真实模型鉴权与回复。
已保存的 Key 不回显，输入框留空保留原值。也兼容已设置的 `SENABOT_MODEL_API_KEY` 和
`SENABOT_EMBEDDING_API_KEY` 环境变量，桌面保存的 Key 优先。

Key 使用 Electron safeStorage 在 Windows 上通过 DPAPI 加密，保存于 Electron 用户数据目录的
`keys.enc`，不进入仓库或浏览器 localStorage。该文件不是 Windows 凭据管理器条目。
后端生命周期日志位于同一用户目录的 `logs/backend.log`，不记录原始模型响应或异常正文。

桌面启动时会自动启动项目 Python 后端，关闭窗口后清理本次创建的后端进程。
若之前在终端手动启动过后端，请先关闭它，再点击设置里的“重启后端”；桌面不会结束外部进程。
后端默认连接地址为 `ws://127.0.0.1:8765`。

## 开发

```powershell
cd frontend
npm.cmd install
npm.cmd run electron:dev
```

开发模式运行 Vite，Electron 同样负责启动后端。`npm.cmd run electron:start` 构建后直接加载
`dist/index.html`，无需 Vite 服务。这仍是源码启动方式，尚未制作安装包或分发 Python 运行环境。

只使用浏览器时执行 `npm.cmd run dev`，后端需手动启动，浏览器不提供密钥保存功能。

角色图片放在本地 `public/characters/sena/sena-neutral.png`，该资源目录已被 Git 忽略。
