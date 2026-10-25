'use strict';

// Synthetic browser/Figma host only. Execute the shipping UI and main scripts.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createHash, randomUUID } = require('node:crypto');
const readline = require('node:readline');
const { createSyntheticFigma } = require('./synthetic_figma.cjs');

async function main() {
  const port = Number(process.argv[2]);
  const token = process.env.DCC_FIGMA_SYNTHETIC_TOKEN;
  if (!Number.isInteger(port) || !token) throw new Error('synthetic_configuration_missing');
  const root = path.resolve(__dirname, '../..');
  const preparedDirectory = process.argv[3] ? path.resolve(process.argv[3]) : null;
  const mode = process.argv[4] || 'default';
  const trialMode = mode.startsWith('native-trial');
  const supportedModes = ['default', 'native-trial', 'native-trial-export-failure',
    'native-trial-wrong-width', 'native-trial-wrong-fill'];
  if (!supportedModes.includes(mode) || (trialMode && !preparedDirectory)) {
    throw new Error('synthetic_configuration_invalid');
  }
  const fixture = createSyntheticFigma({ now: Date.now() });
  if (trialMode) {
    // The native-trial command requires an empty page. Keep other fixture users unchanged.
    fixture.page.children.splice(0);
    fixture.nodes.delete(fixture.frame.id);
  }
  if (mode === 'native-trial-wrong-width') {
    const createFrame = fixture.api.createFrame;
    fixture.api.createFrame = () => {
      const node = createFrame();
      const resize = node.resize.bind(node);
      node.resize = (width, height) => resize(width + 1, height);
      return node;
    };
  }
  if (mode === 'native-trial-wrong-fill') {
    let changing = false;
    fixture.hooks.mutation = write => {
      if (changing || write[0] !== 'set' || write[2] !== 'fills') return;
      const color = write[3][0] && write[3][0].color;
      if (!color || color.r !== 0 || color.g !== 170 / 255 || color.b !== 136 / 255) return;
      changing = true;
      try {
        fixture.nodes.get(write[1]).fills = [{ type: 'SOLID', color: { r: 1, g: 0, b: 0 } }];
      } finally { changing = false; }
    };
  }
  fixture.hooks.export = async (node, options) => {
    if (options.format === 'SVG') {
      if (mode === 'native-trial-export-failure') throw new Error('synthetic_export_failure');
      return new Uint8Array(Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'));
    }
    return new Uint8Array(Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2P0AAAAASUVORK5CYII=',
      'base64'));
  };
  const elements = new Map();
  for (const id of ['pair-form', 'port', 'token', 'connect', 'disconnect', 'status']) {
    elements.set(id, { value: '', disabled: false, textContent: '', events: {},
      addEventListener(name, callback) { this.events[name] = callback; } });
  }
  elements.get('port').value = String(port);
  elements.get('token').value = token;
  const windowObject = { addEventListener() {}, onmessage: null };
  const parentObject = { postMessage(message) {
    queueMicrotask(() => fixture.api.ui.onmessage(message.pluginMessage));
  } };
  fixture.api.showUI = () => {};
  fixture.api.on = () => {};
  fixture.api.ui = { postMessage(message) {
    queueMicrotask(() => windowObject.onmessage({ source: parentObject, data: { pluginMessage: message } }));
  } };
  const pluginDirectory = preparedDirectory || path.join(root, 'plugin');
  const html = fs.readFileSync(path.join(pluginDirectory, 'ui.html'), 'utf8');
  const code = preparedDirectory ? fs.readFileSync(path.join(preparedDirectory, 'code.js'), 'utf8') : null;
  const hostContext = vm.createContext({ figma: fixture.api, __html__: html, Uint8Array });
  if (preparedDirectory) {
    vm.runInContext(code, hostContext);
  } else {
    vm.runInContext(fs.readFileSync(path.join(root, 'plugin/runtime.js'), 'utf8'), hostContext);
    vm.runInContext(fs.readFileSync(path.join(root, 'plugin/main.js'), 'utf8'), hostContext);
  }
  const uiContext = vm.createContext({
    window: windowObject, parent: parentObject,
    document: { getElementById(id) { return elements.get(id); } },
    crypto: { randomUUID }, AbortController, setTimeout, clearTimeout,
    fetch(url, options) {
      const headers = new Headers(options.headers);
      headers.set('Origin', 'null');
      return fetch(url, { ...options, headers });
    },
  });
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script, uiContext);
  async function pair() {
    elements.get('token').value = token;
    await elements.get('pair-form').events.submit({ preventDefault() {} });
    if (!elements.get('status').textContent.startsWith('Connected')) throw new Error('synthetic_pairing_failed');
  }
  async function waitFor(predicate) {
    const deadline = Date.now() + 5000;
    while (!predicate()) {
      if (Date.now() >= deadline) throw new Error('synthetic_state_timeout');
      await new Promise(resolve => setTimeout(resolve, 5));
    }
  }
  await pair();
  if (elements.get('token').value !== '' || fixture.writes.length !== 0) throw new Error('read_only_pairing_failed');
  process.stdout.write(JSON.stringify({ ready: true, evidence: 'synthetic-shipping-ui-and-main',
    prepared_bundle: !!preparedDirectory, mode,
    code_sha256: code === null ? null : createHash('sha256').update(code).digest('hex') }) + '\n');
  let commands = Promise.resolve();
  readline.createInterface({ input: process.stdin }).on('line', line => {
    commands = commands.then(async () => {
    if (line === 'inspect') {
      process.stdout.write(JSON.stringify({ writes: fixture.writes, calls: fixture.calls,
        marker: fixture.marker(), node_count: fixture.nodes.size,
        evidence: 'synthetic', native_acceptance: 'not_run' }) + '\n');
    } else if (line === 'disconnect') {
      elements.get('disconnect').events.click();
    } else if (line === 'reconnect' && trialMode) {
      const writes = fixture.writes.length;
      elements.get('disconnect').events.click();
      await waitFor(() => elements.get('status').textContent === 'Disconnected.');
      await pair();
      if (fixture.writes.length !== writes) throw new Error('read_only_reconnect_failed');
      process.stdout.write(JSON.stringify({ reconnected: true, evidence: 'synthetic-plugin-reconnection',
        native_acceptance: 'not_run' }) + '\n');
    }
    }).catch(() => { process.stderr.write('Synthetic command failed.\n'); process.exit(1); });
  });
}

main().catch(() => { process.stderr.write('Synthetic peer failed.\n'); process.exit(1); });
