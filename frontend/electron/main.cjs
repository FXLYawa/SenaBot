const { app, BrowserWindow, ipcMain, safeStorage } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const net = require("node:net");
const { spawn } = require("node:child_process");
const root = path.resolve(__dirname, "../..");
const development = process.argv.includes("--dev");
let window, child, busy = false, quitting = false;
let state = { running: false, message: "请填写 API Key 后启动", modelSaved: false, embeddingSaved: false };
const keyFile = () => path.join(app.getPath("userData"), "keys.enc");
function readKeys() {
  if (!fs.existsSync(keyFile())) return {};
  if (!safeStorage.isEncryptionAvailable()) throw new Error("系统密钥加密服务不可用");
  return JSON.parse(safeStorage.decryptString(fs.readFileSync(keyFile())));
}
function effectiveKeys() {
  const saved = readKeys();
  return { model: saved.model || process.env.SENABOT_MODEL_API_KEY || "",
    embedding: saved.embedding || process.env.SENABOT_EMBEDDING_API_KEY || "" };
}
function status() {
  try { const keys = effectiveKeys(); state.modelSaved = !!keys.model; state.embeddingSaved = !!keys.embedding; }
  catch { state.message = "无法读取保存的密钥，请重新填写"; }
  return { ...state, busy };
}
function portOpen() {
  return new Promise(resolve => {
    const socket = net.createConnection({ host: "127.0.0.1", port: 8765 });
    const finish = value => { socket.destroy(); resolve(value); };
    socket.setTimeout(300);
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
    socket.once("timeout", () => finish(false));
  });
}
async function stopBackend() {
  const current = child;
  if (!current) return;
  await new Promise(resolve => {
    current.once("close", resolve);
    current.kill();
  });
}
async function startBackend() {
  state.running = false;
  const keys = effectiveKeys();
  if (!keys.model || !keys.embedding) { state.message = "请填写两个 API Key 后启动"; return; }
  if (await portOpen()) throw new Error("8765 端口已占用，请先关闭手动启动的后端");
  const python = path.join(root, ".venv", "Scripts", "python.exe");
  if (!fs.existsSync(python)) throw new Error("未找到项目 Python 虚拟环境，请先安装后端依赖");
  const logDir = path.join(app.getPath("userData"), "logs");
  fs.mkdirSync(logDir, { recursive: true });
  const log = fs.createWriteStream(path.join(logDir, "backend.log"), { flags: "a" });
  const proc = spawn(python, ["-u", path.join(root, "src/main.py")], {
    cwd: root, windowsHide: true,
    env: { ...process.env, SENABOT_MODEL_API_KEY: keys.model, SENABOT_EMBEDDING_API_KEY: keys.embedding },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child = proc;
  // 不落盘原始异常正文，避免上游错误意外携带凭证或对话内容。
  for (const stream of [proc.stdout, proc.stderr]) stream.on("data", () => {
    log.write(`${new Date().toISOString()} backend diagnostic output received\n`);
  });
  proc.on("error", () => { state.message = "后端进程启动失败"; });
  proc.on("close", code => {
    log.end(`${new Date().toISOString()} backend exited (${code})\n`);
    if (child === proc) { child = null; state.running = false; state.message = `后端已退出（${code}），请检查依赖与配置`; }
  });
  state.message = "正在启动后端…";
  for (let i = 0; i < 100; i++) {
    await new Promise(resolve => setTimeout(resolve, 100));
    if (proc.exitCode !== null || child !== proc) throw new Error("后端启动失败，请检查 Python 依赖和配置");
    if (await portOpen()) { state.running = true; state.message = "后端已启动，可以聊天"; return; }
  }
  await stopBackend();
  throw new Error("后端启动超时");
}
async function restart() {
  if (busy) return status();
  busy = true;
  try { await stopBackend(); await startBackend(); }
  catch (e) { state.message = e.message; }
  finally { busy = false; }
  return status();
}
function trusted(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame)
    throw new Error("Unsupported sender");
}
function createWindow() {
  window = new BrowserWindow({ title: "SenaBot", width: 1080, height: 760, minWidth: 420, minHeight: 560,
    backgroundColor: "#ffffff", autoHideMenuBar: true, show: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", event => event.preventDefault());
  window.once("ready-to-show", () => window.show());
  if (development) void window.loadURL("http://127.0.0.1:5173");
  else void window.loadFile(path.join(__dirname, "../dist/index.html"));
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => { if (window) { if (window.isMinimized()) window.restore(); window.focus(); } });
  app.whenReady().then(async () => {
    ipcMain.handle("backend:status", event => { trusted(event); return status(); });
    ipcMain.handle("backend:restart", event => { trusted(event); return restart(); });
    ipcMain.handle("backend:keys", async (event, input) => {
      trusted(event);
      if (busy) return status();
      try {
        if (!input || typeof input.model !== "string" || typeof input.embedding !== "string" || input.model.length > 4096 || input.embedding.length > 4096)
          throw new Error("密钥格式无效");
        if (!safeStorage.isEncryptionAvailable()) throw new Error("系统密钥加密服务不可用，无法保存");
        let saved = {};
        try { saved = readKeys(); } catch { /* 允许用新密钥替换损坏的配置。 */ }
        const keys = { model: input.model.trim() || saved.model || process.env.SENABOT_MODEL_API_KEY || "",
          embedding: input.embedding.trim() || saved.embedding || process.env.SENABOT_EMBEDDING_API_KEY || "" };
        if (!keys.model || !keys.embedding) throw new Error("请填写两个 API Key");
        fs.mkdirSync(app.getPath("userData"), { recursive: true });
        const temp = keyFile() + ".tmp";
        fs.writeFileSync(temp, safeStorage.encryptString(JSON.stringify(keys)));
        fs.renameSync(temp, keyFile());
        return await restart();
      } catch (e) { state.message = e.message; return status(); }
    });
    createWindow();
    await restart();
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", event => {
    if (!quitting && child) { event.preventDefault(); quitting = true; void stopBackend().finally(() => app.quit()); }
  });
}
