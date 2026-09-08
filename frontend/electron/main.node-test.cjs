const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const { EventEmitter } = require("node:events");

async function fixture() {
  const files = new Map(), handlers = new Map(), children = [];
  let ready, window, occupied = false;
  class Window extends EventEmitter {
    constructor() { super(); window = this; this.webContents = new EventEmitter(); this.webContents.mainFrame = {}; this.webContents.setWindowOpenHandler = () => {}; }
    loadFile(file) { this.file = file; }
    loadURL(url) { this.url = url; }
  }
  const app = new EventEmitter();
  Object.assign(app, { requestSingleInstanceLock: () => true, whenReady: () => ({then: fn => { ready = fn; }}), getPath: () => '/private', quit: () => {} });
  const mockedFs = {
    existsSync: p => p.endsWith('python.exe') || files.has(p),
    readFileSync: p => files.get(p), mkdirSync() {},
    writeFileSync: (p, value) => files.set(p, value),
    renameSync: (from, to) => { files.set(to, files.get(from)); files.delete(from); },
    createWriteStream: () => ({write() {}, end() {}}),
  };
  const safeStorage = { isEncryptionAvailable: () => true,
    encryptString: text => Buffer.from('encrypted:' + Buffer.from(text).toString('base64')),
    decryptString: buffer => Buffer.from(buffer.toString().slice(10), 'base64').toString() };
  const electron = { app, BrowserWindow: Window, safeStorage,
    ipcMain: {handle: (name, fn) => handlers.set(name, fn)} };
  const net = { createConnection: () => {
    const socket = new EventEmitter(); socket.destroy = () => {}; socket.setTimeout = () => {};
    setImmediate(() => socket.emit(occupied || children.some(c => c.exitCode === null) ? 'connect' : 'error'));
    return socket;
  } };
  function spawn(executable, args, options) {
    if (executable === 'taskkill') {
      const target = children.find(c => String(c.pid) === args[1]);
      assert.deepEqual(Array.from(args).slice(2), ['/T', '/F']);
      target.kill();
      const killer = new EventEmitter(); setImmediate(() => killer.emit('close', 0)); return killer;
    }
    const proc = new EventEmitter(); proc.pid = children.length + 100; proc.exitCode = null; proc.options = options;
    proc.stdout = new EventEmitter(); proc.stderr = new EventEmitter();
    proc.kill = () => { proc.exitCode = 0; setImmediate(() => proc.emit('close', 0)); };
    children.push(proc); return proc;
  }
  const context = vm.createContext({
    require: name => ({electron, 'node:fs': mockedFs, 'node:net': net, 'node:child_process': {spawn}}[name] || require(name)),
    __dirname, process: {argv: [], env: {}, platform: 'win32'}, Buffer,
    setTimeout: fn => setImmediate(fn),
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'main.cjs'), 'utf8'), context);
  await ready();
  const event = {sender: window.webContents, senderFrame: window.webContents.mainFrame};
  return {children, files, window, app, safeStorage, occupy: () => {occupied = true;},
    call: (name, payload) => handlers.get(name)(event, payload),
    untrusted: () => handlers.get('backend:status')({})};
}
test('first launch loads production UI and requests keys without spawning Python', async () => {
  const f = await fixture();
  assert.equal(f.children.length, 0);
  assert.ok(f.window.file.endsWith(path.join('dist', 'index.html')));
  assert.equal(f.call('backend:status').modelSaved, false);
  assert.throws(f.untrusted);
});
test('saving keys encrypts them, starts Python, retains blank values and replaces only owned child', async () => {
  const f = await fixture();
  const result = await f.call('backend:keys', {model: 'secret-model', embedding: 'secret-embed'});
  assert.equal(result.running, true);
  assert.ok(!JSON.stringify(result).includes('secret-'));
  const disk = [...f.files.values()][0].toString();
  assert.ok(!disk.includes('secret-model'));
  assert.equal(f.children[0].options.env.SENABOT_MODEL_API_KEY, 'secret-model');
  assert.equal(f.children[0].options.windowsHide, true);
  await f.call('backend:keys', {model: '', embedding: ''});
  assert.equal(f.children[0].exitCode, 0);
  assert.equal(f.children[1].options.env.SENABOT_EMBEDDING_API_KEY, 'secret-embed');
  let prevented = false;
  f.app.emit('before-quit', {preventDefault: () => {prevented = true;}});
  await new Promise(setImmediate);
  assert.equal(prevented, true);
  assert.equal(f.children[1].exitCode, 0);
});
test('occupied port is reported without creating or killing an external backend', async () => {
  const f = await fixture(); f.occupy();
  const result = await f.call('backend:keys', {model:'m', embedding:'e'});
  assert.equal(result.running, false); assert.match(result.message, /8765/);
  assert.equal(f.children.length, 0);
});
test('unavailable encryption fails closed without saving plaintext', async () => {
  const f = await fixture(); f.safeStorage.isEncryptionAvailable = () => false;
  const result = await f.call('backend:keys', {model:'m', embedding:'e'});
  assert.equal(f.files.size, 0); assert.equal(f.children.length, 0);
  assert.match(result.message, /加密/);
});
