'use strict';

// Synthetic VM lifecycle evidence only; no browser, Figma host or persistence.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const OLD = 'synthetic-main-old-instance';
const CURRENT = 'synthetic-main-current-instance';

function copy(value) { return JSON.parse(JSON.stringify(value)); }
function initialized() {
  return { ok: true, document: { name: 'Synthetic document', page_id: '0:1', page_name: 'Synthetic page', marker: null } };
}
function completed(label = 'synthetic') { return { ok: true, data: { label } }; }
function deferred() {
  let resolvePromise;
  let rejectPromise;
  let settled = false;
  const promise = new Promise((resolve, reject) => { resolvePromise = resolve; rejectPromise = reject; });
  return { promise, resolve(value) { if (!settled) { settled = true; resolvePromise(value); } },
    reject(error) { if (!settled) { settled = true; rejectPromise(error); } } };
}

function createSyntheticMain() {
  const source = fs.readFileSync(require.resolve('../plugin/main.js'), 'utf8');
  const configs = new Map();
  const runtimes = [];
  const posted = [];
  const events = new Map();
  const gates = [];
  const figma = {
    ui: { postMessage(message) { posted.push(copy(message)); } },
    showUI() {},
    on(name, callback) { events.set(name, callback); },
  };
  const context = vm.createContext({ figma, __html__: '<p>Synthetic UI placeholder</p>', queueMicrotask,
    createFigmaRuntime(api, options) {
      assert.equal(api, figma);
      const config = configs.get(options.instanceId) || {};
      const record = { instanceId: options.instanceId, closed: false, closeCalls: 0, initializeCalls: 0,
        dispatchCalls: [], writes: [], activeDispatches: 0, maxActiveDispatches: 0 };
      const runtime = {
        async initialize() {
          record.initializeCalls += 1;
          return config.initialize ? await config.initialize(record) : initialized();
        },
        async dispatch(method, params) {
          record.dispatchCalls.push({ method, params: copy(params) });
          record.activeDispatches += 1;
          record.maxActiveDispatches = Math.max(record.maxActiveDispatches, record.activeDispatches);
          try {
            const result = config.dispatch ? await config.dispatch(method, params, record) : completed(method);
            // The production runtime owns document guards. The stub represents
            // close invalidation without assigning any old write to a new one.
            if (!record.closed) record.writes.push({ method, params: copy(params) });
            return result;
          } finally { record.activeDispatches -= 1; }
        },
        close() { record.closeCalls += 1; record.closed = true; },
      };
      record.runtime = runtime;
      runtimes.push(record);
      return runtime;
    },
  });
  vm.runInContext(source, context, { filename: 'synthetic-production-main.js' });
  const flush = async () => { await new Promise(resolve => setImmediate(resolve)); };
  const emit = message => figma.ui.onmessage(message);
  const init = instanceId => emit({ type: 'initialize', instance_id: instanceId });
  const stop = instanceId => emit({ type: 'stop', instance_id: instanceId });
  const request = (instanceId, requestId, label = 'synthetic', params = {}) => emit({
    type: 'request', instance_id: instanceId, request_id: requestId, method: label, params,
  });
  async function initialize(instanceId) {
    init(instanceId); await flush();
    assert.ok(posted.some(message => message.type === 'initialized' && message.instance_id === instanceId && message.result.ok),
      'The current session must initialize without waiting for a stopped session');
    return runtimes.findLast(record => record.instanceId === instanceId);
  }
  const gate = () => { const value = deferred(); gates.push(value); return value; };
  async function cleanup() {
    if (events.has('close')) events.get('close')();
    for (const value of gates) value.resolve(completed('synthetic-cleanup'));
    await flush(); await flush();
  }
  return { configs, runtimes, posted, events, emit, init, stop, request, initialize, gate, flush, cleanup,
    current: instanceId => runtimes.findLast(record => record.instanceId === instanceId) };
}

test('synthetic main: stopped initialization may remain pending while a new session initializes', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const old = h.gate();
  h.configs.set(OLD, { initialize: () => old.promise });
  h.init(OLD); await h.flush();
  assert.equal(h.current(OLD).initializeCalls, 1);
  h.stop(OLD);
  assert.equal(h.current(OLD).closeCalls, 1);
  const current = await h.initialize(CURRENT);
  assert.equal(current.initializeCalls, 1);
  assert.equal(current.closeCalls, 0);
  assert.equal(h.posted.some(message => message.instance_id === OLD), false);
});

test('synthetic main: stopped dispatch may remain pending while a new session initializes', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const old = h.gate();
  h.configs.set(OLD, { dispatch: () => old.promise });
  await h.initialize(OLD);
  h.request(OLD, 'old-request'); await h.flush();
  assert.equal(h.current(OLD).dispatchCalls.length, 1);
  h.stop(OLD);
  const current = await h.initialize(CURRENT);
  assert.equal(current.closeCalls, 0);
  assert.equal(h.posted.some(message => message.type === 'response' && message.request_id === 'old-request'), false);
});

test('synthetic main: old resolution and rejection cannot post, close or dispatch into a replacement session', async t => {
  for (const operation of ['initialize', 'dispatch']) for (const settlement of ['resolve', 'reject']) {
    await t.test(`${operation}: ${settlement}`, async subtest => {
      const h = createSyntheticMain(); subtest.after(h.cleanup);
      const old = h.gate();
      h.configs.set(OLD, { [operation]: () => old.promise });
      if (operation === 'initialize') { h.init(OLD); await h.flush(); }
      else { await h.initialize(OLD); h.request(OLD, 'old-request', 'old.write'); await h.flush(); }
      const oldRuntime = h.current(OLD);
      // Initialize itself replaces the old session, without a preceding stop.
      const current = await h.initialize(CURRENT);
      assert.equal(oldRuntime.closeCalls, 1);
      const before = h.posted.length;
      if (settlement === 'resolve') old.resolve(operation === 'initialize' ? initialized() : completed('late-old'));
      else old.reject(new Error('synthetic-old-host-error'));
      await h.flush(); await h.flush();
      assert.equal(h.posted.length, before, 'Stale success and failure packets must both be suppressed');
      assert.equal(current.closeCalls, 0);
      assert.deepEqual(oldRuntime.writes, []);
      assert.deepEqual(current.dispatchCalls, []);
      h.request(CURRENT, 'new-request', 'new.write'); await h.flush();
      assert.equal(current.closeCalls, 0);
      assert.deepEqual(current.dispatchCalls.map(call => call.method), ['new.write']);
      assert.equal(current.writes.length, 1);
      assert.ok(h.posted.some(message => message.type === 'response' && message.instance_id === CURRENT &&
        message.request_id === 'new-request' && message.result.ok));
    });
  }
});

test('synthetic main: requests wait for initialization and remain serial inside one session', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const initializing = h.gate(); const first = h.gate(); const second = h.gate();
  let dispatchIndex = 0;
  h.configs.set(CURRENT, { initialize: () => initializing.promise,
    dispatch: () => [first, second][dispatchIndex++].promise });
  h.init(CURRENT);
  h.request(CURRENT, 1, 'first.write');
  h.request(CURRENT, 2, 'second.write');
  await h.flush();
  const current = h.current(CURRENT);
  assert.deepEqual(current.dispatchCalls, []);
  initializing.resolve(initialized()); await h.flush();
  assert.deepEqual(current.dispatchCalls.map(call => call.method), ['first.write']);
  assert.equal(current.activeDispatches, 1);
  first.resolve(completed('first')); await h.flush();
  assert.deepEqual(current.dispatchCalls.map(call => call.method), ['first.write', 'second.write']);
  assert.equal(current.activeDispatches, 1);
  second.resolve(completed('second')); await h.flush();
  assert.equal(current.maxActiveDispatches, 1);
  assert.deepEqual(h.posted.filter(message => message.type === 'response').map(message => message.request_id), [1, 2]);
});

test('synthetic main: requests queued in a stopped session never reach either runtime', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const first = h.gate();
  h.configs.set(OLD, { dispatch: () => first.promise });
  await h.initialize(OLD);
  h.request(OLD, 1, 'old.first');
  h.request(OLD, 2, 'old.queued');
  await h.flush();
  assert.deepEqual(h.current(OLD).dispatchCalls.map(call => call.method), ['old.first']);
  h.stop(OLD);
  const current = await h.initialize(CURRENT);
  first.resolve(completed('old-first')); await h.flush(); await h.flush();
  assert.deepEqual(h.current(OLD).dispatchCalls.map(call => call.method), ['old.first']);
  assert.deepEqual(current.dispatchCalls, []);
  assert.equal(current.closeCalls, 0);
  assert.equal(h.posted.some(message => message.type === 'response' && message.instance_id === OLD), false);
});

test('synthetic main: an incoming foreign instance receives an immediate correlated stale response', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const pending = h.gate();
  h.configs.set(CURRENT, { dispatch: () => pending.promise });
  await h.initialize(CURRENT);
  h.request(CURRENT, 'current-pending'); await h.flush();
  h.request(OLD, 'foreign-request'); await h.flush();
  assert.deepEqual(h.posted.find(message => message.type === 'response' && message.request_id === 'foreign-request'), {
    type: 'response', instance_id: OLD, request_id: 'foreign-request', result: { ok: false, error: 'stale_instance' },
  });
  assert.equal(h.current(CURRENT).dispatchCalls.length, 1);
  assert.equal(h.current(CURRENT).closeCalls, 0);
  assert.equal(h.posted.some(message => message.type === 'response' && message.request_id === 'current-pending'), false);
});

test('synthetic main: strict fields and request-ID bounds preserve the current session', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const current = await h.initialize(CURRENT);
  const before = h.posted.length;
  h.emit({ type: 'initialize', instance_id: OLD, extra: true });
  h.emit({ type: 'stop', instance_id: CURRENT, extra: true });
  h.stop(OLD);
  for (const id of [-1, 0.5, '', 'x'.repeat(201), null]) h.request(CURRENT, id);
  h.emit({ type: 'request', instance_id: CURRENT, request_id: 12, method: 'extra', params: {}, extra: true });
  await h.flush();
  assert.equal(h.posted.length, before);
  assert.deepEqual(current.dispatchCalls, []);
  assert.equal(current.closeCalls, 0);
  assert.equal(h.runtimes.length, 1);
  for (const id of [0, 'initialize', Number.MAX_SAFE_INTEGER]) h.request(CURRENT, id);
  await h.flush();
  assert.deepEqual(h.posted.filter(message => message.type === 'response').map(message => message.request_id),
    [0, 'initialize', Number.MAX_SAFE_INTEGER]);
});

test('synthetic main: Figma close invalidates the in-flight session and its queued requests', async t => {
  const h = createSyntheticMain(); t.after(h.cleanup);
  const pending = h.gate();
  h.configs.set(CURRENT, { dispatch: () => pending.promise });
  const current = await h.initialize(CURRENT);
  h.request(CURRENT, 1, 'first.write');
  h.request(CURRENT, 2, 'queued.write'); await h.flush();
  assert.equal(current.dispatchCalls.length, 1);
  h.events.get('close')();
  assert.equal(current.closed, true);
  assert.equal(current.closeCalls, 1);
  pending.resolve(completed('late-close')); await h.flush(); await h.flush();
  assert.equal(current.dispatchCalls.length, 1);
  assert.deepEqual(current.writes, []);
  assert.equal(h.posted.some(message => message.type === 'response' && message.instance_id === CURRENT), false);
});
