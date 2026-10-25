'use strict';

// Synthetic Figma Plugin API evidence only. This harness does not establish
// execution in a real Figma host or native document persistence.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createFigmaRuntime } = require('../plugin/runtime.js');
const { createSyntheticFigma } = require('./support/synthetic_figma.cjs');

const INSTANCE = 'synthetic-plugin-instance';
const MARKER_KEY = 'dcc_mcp_document_id';
const NOW = 1_800_000_000_000;
const MAX_EXPORT_BYTES = 1024 * 1024;

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function createHarness(options) {
  const h = createSyntheticFigma(options);
  h.runtime = createFigmaRuntime(h.api, { instanceId: h.instanceId, now: h.now });
  return h;
}

function frameFields(extra = {}) {
  return { name: 'Created frame', width: 320, height: 240,
    x: 12, y: -24, fill: '#3366FF', ...extra };
}

function assertError(result, code) {
  assert.deepEqual(result, { ok: false, error: code });
}

function assertDocument(result, harness, marker = harness.marker() || null) {
  assert.equal(result.ok, true);
  assert.deepEqual(result.document, {
    name: harness.root.name,
    page_id: harness.page.id,
    page_name: harness.page.name,
    marker,
  });
}

test('synthetic: initialize and read await page loading and never write markers', async () => {
  const h = createHarness();
  const gate = deferred();
  let finished = false;
  h.hooks.load = () => gate.promise;
  const initializing = h.runtime.initialize().then((result) => {
    finished = true;
    return result;
  });
  await Promise.resolve();
  assert.equal(finished, false);
  assert.deepEqual(h.writes, []);
  gate.resolve();
  const initial = await initializing;
  assertDocument(initial, h, null);
  h.hooks.load = null;

  const document = await h.runtime.dispatch('document.read', h.params());
  assertDocument(document, h, null);
  assert.ok(Array.isArray(document.data.nodes));
  assert.equal(typeof document.data.truncated, 'boolean');
  assert.ok(document.data.nodes.some((node) => node.id === h.frame.id));
  const node = await h.runtime.dispatch('node.read', h.params({ node_id: h.frame.id }));
  assertDocument(node, h, null);
  assert.equal(node.data.id, h.frame.id);
  assert.equal(node.data.type, 'FRAME');
  assert.ok(h.calls.filter((call) => call[0] === 'loadAsync').length >= 3);
  assert.deepEqual(h.writes, []);
  assert.equal(h.marker(), '');
});

test('synthetic: document.read caps direct children at 200 and reports truncation', async () => {
  const h = createHarness();
  for (let index = 0; index < 205; index += 1) {
    h.makeNode({ parent: h.page, name: `Synthetic frame ${index}` });
  }
  await h.runtime.initialize();
  const result = await h.runtime.dispatch('document.read', h.params({ limit: 200 }));
  assertDocument(result, h, null);
  assert.equal(result.data.nodes.length, 200);
  assert.equal(result.data.truncated, true);
  assert.deepEqual(result.data.nodes.map((node) => node.id),
    h.page.children.slice(0, 200).map((node) => node.id));
  assert.deepEqual(h.writes, []);
});

test('synthetic: document.read defaults to 100 direct children', async () => {
  const h = createHarness();
  for (let index = 0; index < 105; index += 1) {
    h.makeNode({ parent: h.page, name: `Synthetic frame ${index}` });
  }
  await h.runtime.initialize();
  const result = await h.runtime.dispatch('document.read', h.params());
  assertDocument(result, h, null);
  assert.equal(result.data.nodes.length, 100);
  assert.equal(result.data.truncated, true);
  assert.deepEqual(result.data.nodes.map((node) => node.id),
    h.page.children.slice(0, 100).map((node) => node.id));
  assert.deepEqual(h.writes, []);
});

test('synthetic: document.read respects an explicit small limit', async () => {
  const h = createHarness();
  for (let index = 0; index < 3; index += 1) {
    h.makeNode({ parent: h.page, name: `Synthetic frame ${index}` });
  }
  await h.runtime.initialize();
  const result = await h.runtime.dispatch('document.read', h.params({ limit: 2 }));
  assertDocument(result, h, null);
  assert.equal(result.data.nodes.length, 2);
  assert.equal(result.data.truncated, true);
  assert.deepEqual(result.data.nodes.map((node) => node.id),
    h.page.children.slice(0, 2).map((node) => node.id));
  assert.deepEqual(h.writes, []);
});

test('synthetic: invalid document.read limits fail without document writes', async (t) => {
  for (const limit of [0, 201, 1.5, '10', true]) {
    await t.test(`${typeof limit}: ${String(limit)}`, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      assertError(await h.runtime.dispatch('document.read', h.params({ limit })), 'invalid_arguments');
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: create, update, read and export use typed Plugin API methods', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  const created = await h.runtime.dispatch('frame.create', h.params(frameFields()));
  assertDocument(created, h, INSTANCE);
  const id = created.data.id;
  assert.equal(created.data.name, 'Created frame');
  assert.equal(created.data.width, 320);
  assert.equal(created.data.height, 240);
  assert.equal(created.data.fill, '#3366FF');
  assert.equal(h.marker(), INSTANCE);
  assert.equal(h.writes.filter((write) => write[0] === 'createFrame').length, 1);
  assert.deepEqual(h.writes.filter((write) => write[0] === 'setPluginData'),
    [['setPluginData', MARKER_KEY, INSTANCE]]);
  const nativeFrame = h.nodes.get(id);
  assert.equal(nativeFrame.parent, h.page);
  assert.deepEqual(nativeFrame.fills, [{ type: 'SOLID', color: {
    r: 0x33 / 255, g: 0x66 / 255, b: 1,
  } }]);

  const updated = await h.runtime.dispatch('frame.update', h.params({ node_id: id,
    name: 'Updated frame', width: 480, x: -7, fill: '#FF0000' }));
  assertDocument(updated, h, INSTANCE);
  assert.equal(updated.data.name, 'Updated frame');
  assert.equal(updated.data.width, 480);
  assert.equal(updated.data.height, 240);
  assert.equal(updated.data.x, -7);
  const read = await h.runtime.dispatch('node.read', h.params({ node_id: id }));
  assertDocument(read, h, INSTANCE);
  assert.equal(read.data.name, 'Updated frame');
  assert.equal(read.data.width, 480);
  assert.equal(read.data.fill, '#FF0000');
  assert.equal(h.writes.filter((write) => write[0] === 'setPluginData').length, 1);

  const exported = await h.runtime.dispatch('node.export', h.params({ node_id: id, format: 'PNG' }));
  assertDocument(exported, h, INSTANCE);
  assert.deepEqual(exported.data, { node_id: id, format: 'PNG', mime_type: 'image/png',
    data_base64: 'iVBORw==', byte_length: 4 });
  assert.ok(h.calls.some((call) => call[0] === 'exportAsync' && call[1] === id
    && call[2].format === 'PNG'));
  assert.ok(h.writes.some((write) => write[0] === 'resize' && write[1] === id
    && write[2] === 480 && write[3] === 240));
});

test('synthetic: an existing marker is preserved on writes', async () => {
  const h = createHarness({ marker: 'existing-document-marker' });
  await h.runtime.initialize();
  const updated = await h.runtime.dispatch('frame.update', h.params({
    node_id: h.frame.id, name: 'Renamed',
  }));
  assertDocument(updated, h, 'existing-document-marker');
  assert.equal(h.marker(), 'existing-document-marker');
  assert.equal(h.writes.filter((write) => write[0] === 'setPluginData').length, 0);
});

test('synthetic: updating an unmarked document creates its marker once', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  const updated = await h.runtime.dispatch('frame.update', h.params({
    node_id: h.frame.id, name: 'First mutation',
  }));
  assertDocument(updated, h, INSTANCE);
  assert.equal(h.marker(), INSTANCE);
  assert.deepEqual(h.writes.filter((write) => write[0] === 'setPluginData'),
    [['setPluginData', MARKER_KEY, INSTANCE]]);
});

test('synthetic: frame numeric and name boundary values are accepted', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  const result = await h.runtime.dispatch('frame.create', h.params(frameFields({
    name: 'x'.repeat(120), width: 1, height: 8192,
    x: -1_000_000, y: 1_000_000, fill: '#aAbBcC',
  })));
  assertDocument(result, h, INSTANCE);
  assert.equal(result.data.width, 1);
  assert.equal(result.data.height, 8192);
});

test('synthetic: invalid create arguments reject before any document write', async (t) => {
  const cases = [
    ...Object.keys(frameFields()).map((key) => [`missing ${key}`, (value) => { delete value[key]; }]),
    ['unknown field', (value) => { value.script = 'not executable'; }],
    ['empty name', (value) => { value.name = ''; }],
    ['overlong name', (value) => { value.name = 'x'.repeat(121); }],
    ['non-string name', (value) => { value.name = 7; }],
    ['zero width', (value) => { value.width = 0; }],
    ['oversized height', (value) => { value.height = 8193; }],
    ['non-numeric width', (value) => { value.width = '320'; }],
    ['NaN width', (value) => { value.width = NaN; }],
    ['infinite height', (value) => { value.height = Infinity; }],
    ['out-of-bounds x', (value) => { value.x = -1_000_001; }],
    ['infinite y', (value) => { value.y = Infinity; }],
    ['short hex fill', (value) => { value.fill = '#fff'; }],
    ['alpha fill', (value) => { value.fill = '#3366FF00'; }],
    ['invalid hex fill', (value) => { value.fill = '#GG0000'; }],
    ['object fill', (value) => { value.fill = { r: 1, g: 0, b: 0 }; }],
  ];
  for (const [label, change] of cases) {
    await t.test(label, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      const fields = frameFields();
      change(fields);
      assertError(await h.runtime.dispatch('frame.create', h.params(fields)), 'invalid_arguments');
      assert.deepEqual(h.writes, []);
      assert.equal(h.marker(), '');
    });
  }
});

test('synthetic: invalid update and export arguments never write', async (t) => {
  const cases = [
    ['empty update', 'frame.update', { node_id: '1:1' }],
    ['missing node id', 'frame.update', { name: 'A' }],
    ['unknown update field', 'frame.update', { node_id: '1:1', name: 'A', script: 'x' }],
    ['invalid update width', 'frame.update', { node_id: '1:1', width: -1 }],
    ['unsupported export format', 'node.export', { node_id: '1:1', format: 'PDF' }],
    ['missing export format', 'node.export', { node_id: '1:1' }],
    ['export unknown field', 'node.export', { node_id: '1:1', format: 'PNG', script: 'x' }],
    ['empty node id', 'node.read', { node_id: '' }],
  ];
  for (const [label, method, fields] of cases) {
    await t.test(label, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      assertError(await h.runtime.dispatch(method, h.params(fields)), 'invalid_arguments');
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: every request requires a complete, typed binding and deadline', async (t) => {
  for (const key of ['expected_plugin_instance', 'page_id', 'document_marker', 'deadline_ms']) {
    await t.test(`missing ${key}`, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      const params = h.params();
      delete params[key];
      assertError(await h.runtime.dispatch('document.read', params), 'invalid_arguments');
      assert.deepEqual(h.writes, []);
    });
  }
  for (const [key, value] of [['expected_plugin_instance', 4], ['page_id', 4],
    ['document_marker', {}], ['deadline_ms', 'later'], ['deadline_ms', Infinity]]) {
    await t.test(`invalid ${key}: ${String(value)}`, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      assertError(await h.runtime.dispatch('document.read', h.params({ [key]: value })),
        'invalid_arguments');
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: stale instance, scope, marker and deadline fail without mutation', async (t) => {
  const cases = [
    ['stale instance', { expected_plugin_instance: 'another-plugin' }, 'stale_instance'],
    ['wrong page', { page_id: '0:2' }, 'scope_mismatch'],
    ['wrong marker', { document_marker: 'other-document' }, 'scope_mismatch'],
    ['expired deadline', { deadline_ms: NOW - 1 }, 'deadline_exceeded'],
    ['deadline reached', { deadline_ms: NOW }, 'deadline_exceeded'],
  ];
  for (const [label, overrides, code] of cases) {
    await t.test(label, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      assertError(await h.runtime.dispatch('frame.create', h.params({
        ...frameFields(), ...overrides,
      })), code);
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: matching an externally changed marker cannot rebind the runtime', async () => {
  const h = createHarness({ marker: 'original-marker' });
  await h.runtime.initialize();
  h.setMarker('external-marker');
  const params = h.params();
  assert.equal(params.document_marker, 'external-marker');
  assertError(await h.runtime.dispatch('frame.create', { ...params, ...frameFields() }), 'scope_mismatch');
  assert.deepEqual(h.writes, []);
});

test('synthetic: unknown methods and non-object arguments are fixed-code failures', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  assertError(await h.runtime.dispatch('execute', h.params()), 'unsupported_method');
  for (const params of [null, undefined, [], 'arbitrary source']) {
    assertError(await h.runtime.dispatch('frame.create', params), 'invalid_arguments');
  }
  assert.deepEqual(h.writes, []);
});

test('synthetic: changed page or marker during page loading rejects before create', async (t) => {
  for (const change of ['page', 'marker', 'root', 'deadline', 'closed']) {
    await t.test(change, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks.load = async () => {
        if (change === 'page') h.figma.currentPage = h.otherPage;
        if (change === 'marker') h.setMarker('changed-marker');
        if (change === 'root') h.figma.root = { ...h.root };
        if (change === 'deadline') h.setNow(NOW + 10_000);
        if (change === 'closed') h.runtime.close();
      };
      const code = change === 'deadline' ? 'deadline_exceeded'
        : change === 'closed' ? 'stale_instance' : 'scope_mismatch';
      assertError(await h.runtime.dispatch('frame.create', h.params(frameFields())), code);
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: changed scope during lookup rejects before update writes', async (t) => {
  for (const change of ['page', 'marker', 'root', 'deadline', 'closed']) {
    await t.test(change, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks.lookup = async () => {
        if (change === 'page') h.figma.currentPage = h.otherPage;
        if (change === 'marker') h.setMarker('changed-marker');
        if (change === 'root') h.figma.root = { ...h.root };
        if (change === 'deadline') h.setNow(NOW + 10_000);
        if (change === 'closed') h.runtime.close();
      };
      const code = change === 'deadline' ? 'deadline_exceeded'
        : change === 'closed' ? 'stale_instance' : 'scope_mismatch';
      assertError(await h.runtime.dispatch('frame.update', h.params({
        node_id: h.frame.id, name: 'Must not be applied',
      })), code);
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: scope is rechecked between individual document mutations', async (t) => {
  await t.test('scope changes after the first marker write', async () => {
    const h = createHarness();
    await h.runtime.initialize();
    h.hooks.mutation = (write) => {
      if (write[0] === 'setPluginData') h.figma.currentPage = h.otherPage;
    };
    assertError(await h.runtime.dispatch('frame.create', h.params(frameFields())), 'scope_mismatch');
    assert.deepEqual(h.writes, [['setPluginData', MARKER_KEY, INSTANCE]]);
  });
  await t.test('scope changes after frame creation', async () => {
    const h = createHarness({ marker: 'existing-marker' });
    await h.runtime.initialize();
    h.hooks.mutation = (write) => {
      if (write[0] === 'createFrame') h.figma.currentPage = h.otherPage;
    };
    assertError(await h.runtime.dispatch('frame.create', h.params(frameFields())), 'scope_mismatch');
    assert.deepEqual(h.writes, [['createFrame']]);
  });
  await t.test('scope changes after the first update field', async () => {
    const h = createHarness({ marker: 'existing-marker' });
    await h.runtime.initialize();
    h.hooks.mutation = () => { h.figma.currentPage = h.otherPage; };
    assertError(await h.runtime.dispatch('frame.update', h.params({
      node_id: h.frame.id, name: 'One mutation', width: 300, x: 40,
    })), 'scope_mismatch');
    assert.equal(h.writes.length, 1);
  });
});

test('synthetic: node lookup enforces page bounds and operation-specific node types', async (t) => {
  for (const method of ['node.read', 'frame.update', 'node.export']) {
    for (const kind of ['missing', 'non-frame', 'outside-page']) {
      await t.test(`${method}: ${kind}`, async () => {
        const h = createHarness();
        const node = kind === 'missing' ? { id: 'missing' } : h.makeNode({
          type: kind === 'non-frame' ? 'TEXT' : 'FRAME',
          parent: kind === 'outside-page' ? h.otherPage : h.page,
        });
        await h.runtime.initialize();
        const extra = method === 'frame.update' ? { name: 'Invalid target' }
          : method === 'node.export' ? { format: 'PNG' } : {};
        const code = kind === 'missing' ? 'node_not_found'
          : kind === 'non-frame' ? 'unsupported_node' : 'scope_mismatch';
        const result = await h.runtime.dispatch(method, h.params({ node_id: node.id, ...extra }));
        if (method === 'node.read' && kind === 'non-frame') {
          assertDocument(result, h, null);
          assert.equal(result.data.id, node.id);
          assert.equal(result.data.type, 'TEXT');
        } else {
          assertError(result, code);
        }
        assert.deepEqual(h.writes, []);
      });
    }
  }
});

test('synthetic: a nested frame in the bound page supports read, update and export', async () => {
  const h = createHarness({ marker: 'existing-marker' });
  const nested = h.makeNode({ parent: h.frame, name: 'Nested frame' });
  await h.runtime.initialize();
  const read = await h.runtime.dispatch('node.read', h.params({ node_id: nested.id }));
  assertDocument(read, h, 'existing-marker');
  assert.equal(read.data.id, nested.id);
  assert.deepEqual(h.writes, []);
  const updated = await h.runtime.dispatch('frame.update', h.params({
    node_id: nested.id, name: 'Nested updated',
  }));
  assertDocument(updated, h, 'existing-marker');
  assert.equal(updated.data.name, 'Nested updated');
  const exported = await h.runtime.dispatch('node.export', h.params({ node_id: nested.id, format: 'PNG' }));
  assertDocument(exported, h, 'existing-marker');
  assert.equal(exported.data.node_id, nested.id);
});

test('synthetic: SVG export encodes actual bytes without creating a marker', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  const bytes = new TextEncoder().encode('<svg/>');
  h.hooks.export = async () => bytes;
  const result = await h.runtime.dispatch('node.export', h.params({ node_id: h.frame.id, format: 'SVG' }));
  assertDocument(result, h, null);
  assert.deepEqual(result.data, { node_id: h.frame.id, format: 'SVG',
    mime_type: 'image/svg+xml', data_base64: Buffer.from(bytes).toString('base64'),
    byte_length: bytes.byteLength });
  assert.deepEqual(h.writes, []);
});

test('synthetic: export checks the actual byte count at the 1 MiB limit', async (t) => {
  for (const size of [MAX_EXPORT_BYTES, MAX_EXPORT_BYTES + 1]) {
    await t.test(`${size} bytes`, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks.export = async () => new Uint8Array(size);
      const result = await h.runtime.dispatch('node.export', h.params({ node_id: h.frame.id, format: 'PNG' }));
      if (size > MAX_EXPORT_BYTES) {
        assertError(result, 'export_too_large');
        assert.equal(h.calls.filter((call) => call[0] === 'base64Encode').length, 0);
      } else {
        assertDocument(result, h, null);
        assert.equal(result.data.byte_length, size);
        assert.equal(Buffer.from(result.data.data_base64, 'base64').length, size);
      }
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: export requires a nonempty Uint8Array from the Plugin API', async (t) => {
  for (const [label, bytes] of [['ArrayBuffer', new ArrayBuffer(4)],
    ['plain array', [1, 2, 3]], ['string', 'bytes'], ['empty bytes', new Uint8Array(0)]]) {
    await t.test(label, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks.export = async () => bytes;
      assertError(await h.runtime.dispatch('node.export', h.params({
        node_id: h.frame.id, format: 'PNG',
      })), 'host_error');
      assert.deepEqual(h.writes, []);
      assert.equal(h.calls.filter((call) => call[0] === 'base64Encode').length, 0);
    });
  }
});

test('synthetic: changed scope after export awaits suppresses the bytes', async (t) => {
  for (const change of ['page', 'marker', 'root', 'deadline', 'closed']) {
    await t.test(change, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks.export = async () => {
        if (change === 'page') h.figma.currentPage = h.otherPage;
        if (change === 'marker') h.setMarker('changed-marker');
        if (change === 'root') h.figma.root = { ...h.root };
        if (change === 'deadline') h.setNow(NOW + 10_000);
        if (change === 'closed') h.runtime.close();
        return new Uint8Array([1, 2, 3]);
      };
      const code = change === 'deadline' ? 'deadline_exceeded'
        : change === 'closed' ? 'stale_instance' : 'scope_mismatch';
      assertError(await h.runtime.dispatch('node.export', h.params({
        node_id: h.frame.id, format: 'PNG',
      })), code);
      assert.deepEqual(h.writes, []);
      assert.equal(h.calls.filter((call) => call[0] === 'base64Encode').length, 0);
    });
  }
});

test('synthetic: host exceptions become fixed errors without leaking details', async (t) => {
  for (const operation of ['load', 'lookup', 'export']) {
    await t.test(operation, async () => {
      const h = createHarness();
      await h.runtime.initialize();
      h.hooks[operation] = async () => { throw new Error('sensitive host diagnostic'); };
      const method = operation === 'load' ? 'frame.create'
        : operation === 'lookup' ? 'frame.update' : 'node.export';
      const fields = operation === 'load' ? frameFields()
        : operation === 'lookup' ? { node_id: h.frame.id, name: 'A' }
          : { node_id: h.frame.id, format: 'PNG' };
      assertError(await h.runtime.dispatch(method, h.params(fields)), 'host_error');
      assert.deepEqual(h.writes, []);
    });
  }
});

test('synthetic: close invalidates future requests', async () => {
  const h = createHarness();
  await h.runtime.initialize();
  h.runtime.close();
  assertError(await h.runtime.dispatch('document.read', h.params()), 'stale_instance');
  assert.deepEqual(h.writes, []);
});

test('synthetic: node fill snapshots are bounded document RGB values without writes', async (t) => {
  const color = { r: 0, g: 170 / 255, b: 136 / 255 };
  const solid = { type: 'SOLID', color };
  const cases = [
    ['opaque defaults', [solid], '#00AA88'],
    ['explicit defaults', [{ ...solid, visible: true, opacity: 1, blendMode: 'NORMAL' }], '#00AA88'],
    ['empty', [], null],
    ['mixed', Symbol('mixed'), null],
    ['multiple paints', [solid, solid], null],
    ['invisible', [{ ...solid, visible: false }], null],
    ['translucent', [{ ...solid, opacity: 0.5 }], null],
    ['blend mode', [{ ...solid, blendMode: 'MULTIPLY' }], null],
    ['gradient', [{ type: 'GRADIENT_LINEAR' }], null],
    ['image', [{ type: 'IMAGE', get color() { throw new Error('must not read image color'); } }], null],
    ['missing color', [{ type: 'SOLID' }], null],
    ['nonfinite channel', [{ ...solid, color: { ...color, r: NaN } }], null],
    ['negative channel', [{ ...solid, color: { ...color, r: -1 } }], null],
    ['oversized channel', [{ ...solid, color: { ...color, r: 2 } }], null],
    ['nonnumeric channel', [{ ...solid, color: { ...color, r: '0' } }], null],
  ];
  for (const [label, paints, expected] of cases) {
    await t.test(label, async () => {
      const h = createHarness();
      h.frame.fills = paints;
      h.writes.length = 0;
      await h.runtime.initialize();
      const read = await h.runtime.dispatch('node.read', h.params({ node_id: h.frame.id }));
      assertDocument(read, h, null);
      assert.equal(read.data.fill, expected);
      assert.deepEqual(h.writes, []);
    });
  }
});

// Synthetic UI contract: this evaluates the shipped UI script with fake DOM,
// parent messages and HTTP responses. It does not run a browser or Figma host.
function createSyntheticUi(request) {
  const fs = require('node:fs');
  const vm = require('node:vm');
  const html = fs.readFileSync(require.resolve('../plugin/ui.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const events = new Map();
  const elements = new Map();
  for (const id of ['pair-form', 'port', 'token', 'connect', 'disconnect', 'status']) {
    elements.set(id, { value: '', disabled: false, textContent: '',
      addEventListener(type, handler) { events.set(`${id}:${type}`, handler); } });
  }
  elements.get('port').value = '19061';
  elements.get('token').value = 'synthetic-ui-pairing-token';
  const posted = [];
  const fetched = [];
  const responses = [];
  let delivered = false;
  const parent = { postMessage(message) { posted.push(JSON.parse(JSON.stringify(message.pluginMessage))); } };
  const response = (payload) => ({ ok: true, status: payload === null ? 204 : 200,
    async json() { return payload; } });
  const context = vm.createContext({
    document: { getElementById: (id) => elements.get(id) }, parent,
    crypto: { randomUUID: () => 'synthetic-ui-instance' }, AbortController, setTimeout, clearTimeout,
    fetch: async (url, options) => {
      const body = options.body === undefined ? undefined : JSON.parse(options.body);
      fetched.push({ url, options, body });
      if (url.endsWith('/connect')) return response({ connection_id: 'synthetic-connection' });
      if (url.includes('/request?')) {
        if (!delivered) {
          delivered = true;
          return response({ connection_id: 'synthetic-connection', request });
        }
        return new Promise((resolve, reject) => {
          if (options.signal.aborted) reject(new Error('synthetic_abort'));
          else options.signal.addEventListener('abort', () => reject(new Error('synthetic_abort')), { once: true });
        });
      }
      if (url.endsWith('/response')) { responses.push(body); return response(null); }
      if (url.endsWith('/disconnect')) return response(null);
      throw new Error('unexpected_synthetic_http_route');
    },
  });
  context.window = context;
  context.addEventListener = (type, handler) => events.set(`window:${type}`, handler);
  new vm.Script(script, { filename: 'synthetic-ui-script.js' }).runInContext(context);
  const tick = () => new Promise((resolve) => setImmediate(resolve));
  const emit = (message, source = parent) => context.onmessage({ source, data: { pluginMessage: message } });
  async function start() {
    const submitted = events.get('pair-form:submit')({ preventDefault() {} });
    assert.equal(elements.get('token').value, '');
    assert.equal(posted[0].type, 'initialize');
    emit({ type: 'initialized', instance_id: 'synthetic-ui-instance', result: { ok: true,
      document: { name: 'Synthetic UI document', page_id: '0:1', page_name: 'Page', marker: null } } });
    await submitted;
    await tick();
  }
  async function close() {
    events.get('disconnect:click')();
    await tick();
    await tick();
  }
  return { posted, fetched, responses, elements, emit, start, close, tick };
}

test('synthetic UI: Core JSON-RPC request and response categories remain correlated', async (t) => {
  const request = { jsonrpc: '2.0', id: 'initialize', method: 'document.read', params: {} };
  const h = createSyntheticUi(request);
  t.after(h.close);
  await h.start();
  assert.equal(h.posted.filter((message) => message.type === 'request').length, 1);
  const result = { ok: true, document: { marker: null }, data: { nodes: [], truncated: false } };
  h.emit({ type: 'initialized', instance_id: 'synthetic-ui-instance', result });
  h.emit({ type: 'response', instance_id: 'synthetic-ui-instance', request_id: 'initialize', result, extra: true });
  h.emit({ type: 'response', instance_id: 'synthetic-ui-instance', request_id: 'initialize', result }, {});
  await h.tick();
  assert.equal(h.responses.length, 0);
  h.emit({ type: 'response', instance_id: 'synthetic-ui-instance', request_id: 'initialize', result });
  await h.tick();
  assert.deepEqual(h.responses, [{ connection_id: 'synthetic-connection', id: 'initialize', result }]);
  assert.equal(JSON.stringify(h.posted).includes('synthetic-ui-pairing-token'), false);
  assert.equal(h.fetched.some((call) => call.url.includes('synthetic-ui-pairing-token')), false);
  assert.equal(h.fetched.every((call) => call.options.headers.Authorization === 'Bearer synthetic-ui-pairing-token'), true);
});

test('synthetic UI: malformed Core requests stop before dispatch', async (t) => {
  const good = { jsonrpc: '2.0', id: 'synthetic-request', method: 'document.read', params: {} };
  const invalid = [
    ['missing JSON-RPC version', { id: good.id, method: good.method, params: {} }],
    ['wrong JSON-RPC version', { ...good, jsonrpc: '1.0' }],
    ['array params', { ...good, params: [] }],
    ['negative request id', { ...good, id: -1 }],
    ['overlong request id', { ...good, id: 'x'.repeat(201) }],
    ['extra request field', { ...good, extra: true }],
  ];
  for (const [name, request] of invalid) {
    await t.test(name, async (subtest) => {
      const h = createSyntheticUi(request);
      subtest.after(h.close);
      await h.start();
      assert.equal(h.posted.filter((message) => message.type === 'request').length, 0);
      assert.equal(h.posted.filter((message) => message.type === 'stop').length, 1);
      assert.equal(h.responses.length, 0);
      assert.match(h.elements.get('status').textContent, /Connection stopped/);
    });
  }
});
