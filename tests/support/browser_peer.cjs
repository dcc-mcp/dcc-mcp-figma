'use strict';

// Synthetic browser/Figma host only. Execute the shipping UI and main scripts.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { randomUUID } = require('node:crypto');
const readline = require('node:readline');
const { createSyntheticFigma } = require('./synthetic_figma.cjs');

async function main() {
  const port = Number(process.argv[2]);
  const token = process.env.DCC_FIGMA_SYNTHETIC_TOKEN;
  if (!Number.isInteger(port) || !token) throw new Error('synthetic_configuration_missing');
  const root = path.resolve(__dirname, '../..');
  const fixture = createSyntheticFigma({ now: Date.now() });
  fixture.hooks.export = async (node, options) => {
    if (options.format === 'SVG') {
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
  const hostContext = vm.createContext({ figma: fixture.api, __html__: '', Uint8Array });
  vm.runInContext(fs.readFileSync(path.join(root, 'plugin/runtime.js'), 'utf8'), hostContext);
  vm.runInContext(fs.readFileSync(path.join(root, 'plugin/main.js'), 'utf8'), hostContext);
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
  const html = fs.readFileSync(path.join(root, 'plugin/ui.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  vm.runInContext(script, uiContext);
  await elements.get('pair-form').events.submit({ preventDefault() {} });
  if (!elements.get('status').textContent.startsWith('Connected')) throw new Error('synthetic_pairing_failed');
  if (elements.get('token').value !== '' || fixture.writes.length !== 0) throw new Error('read_only_pairing_failed');
  process.stdout.write(JSON.stringify({ ready: true, evidence: 'synthetic-shipping-ui-and-main' }) + '\n');
  readline.createInterface({ input: process.stdin }).on('line', line => {
    if (line === 'inspect') {
      process.stdout.write(JSON.stringify({ writes: fixture.writes, calls: fixture.calls,
        marker: fixture.marker(), node_count: fixture.nodes.size,
        evidence: 'synthetic', native_acceptance: 'not_run' }) + '\n');
    } else if (line === 'disconnect') {
      elements.get('disconnect').events.click();
    }
  });
}

main().catch(() => { process.stderr.write('Synthetic peer failed.\n'); process.exit(1); });
