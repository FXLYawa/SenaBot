# SenaBot Desktop

开发期先启动 Python 核心，再运行 Electron 客户端：

```powershell
cd E:\SenaBot\SenaBot
python src\main.py

# 另一个终端
cd E:\SenaBot\SenaBot\frontend
npm.cmd run electron:dev
```

只在浏览器中验证 UI 时可运行 `npm.cmd run dev`。

```powershell
npm.cmd install
npm.cmd run test
npm.cmd run build
```

`npm.cmd run electron:start` 会先构建前端，再以 Electron 加载生产文件。Python 核心的自动启动、启动令牌和安装包将在后续阶段接入。

角色美术资源放在 `public/characters/sena/`，该目录已被仓库根目录的 `.gitignore` 排除。首次拉取项目后，需要在本地自行放置 `sena-neutral.png`。
