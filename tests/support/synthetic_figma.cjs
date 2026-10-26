'use strict';

// Synthetic Figma Plugin API fixture; this is not a native Figma host.
const assert = require('node:assert/strict');
const INSTANCE = 'synthetic-plugin-instance';
const MARKER_KEY = 'dcc_mcp_document_id';
const NOW = 1_800_000_000_000;

function createSyntheticFigma({ marker = '', now = NOW, instanceId = INSTANCE } = {}) {
  const writes = [];
  const calls = [];
  const hooks = { load: null, lookup: null, export: null, mutation: null };
  const nodes = new Map();
  let markerValue = marker;
  let clock = now;
  let nextId = 10;
  let figma;

  function recordWrite(write) {
    writes.push(write);
    if (hooks.mutation) hooks.mutation(write);
  }

  const root = {
    id: '0:0', type: 'DOCUMENT', name: 'Synthetic document', children: [],
    getPluginData(key) {
      assert.equal(key, MARKER_KEY);
      calls.push(['getPluginData', key]);
      return markerValue;
    },
    setPluginData(key, value) {
      assert.equal(key, MARKER_KEY);
      markerValue = value;
      recordWrite(['setPluginData', key, value]);
    },
  };

  function makePage(id, name) {
    const page = {
      id, name, type: 'PAGE', parent: root, children: [],
      async loadAsync() {
        calls.push(['loadAsync', id]);
        if (hooks.load) await hooks.load(page);
      },
    };
    nodes.set(id, page);
    root.children.push(page);
    return page;
  }

  function makeNode({ id, name = 'Existing frame', type = 'FRAME', parent,
    width = 200, height = 100, x = 5, y = 8 } = {}) {
    const values = { name, width, height, x, y, fills: [] };
    const node = {
      id: id || `1:${nextId++}`, type, parent, children: [], removed: false,
      resize(nextWidth, nextHeight) {
        values.width = nextWidth;
        values.height = nextHeight;
        recordWrite(['resize', node.id, nextWidth, nextHeight]);
      },
      async exportAsync(options) {
        calls.push(['exportAsync', node.id, options]);
        if (hooks.export) return await hooks.export(node, options);
        return new Uint8Array([137, 80, 78, 71]);
      },
    };
    for (const property of ['name', 'x', 'y', 'fills']) {
      Object.defineProperty(node, property, {
        enumerable: true,
        get: () => values[property],
        set(value) {
          values[property] = value;
          recordWrite(['set', node.id, property, value]);
        },
      });
    }
    for (const property of ['width', 'height']) {
      Object.defineProperty(node, property, {
        enumerable: true, get: () => values[property],
      });
    }
    if (parent) parent.children.push(node);
    nodes.set(node.id, node);
    return node;
  }

  const page = makePage('0:1', 'Synthetic page');
  const otherPage = makePage('0:2', 'Other page');
  const frame = makeNode({ id: '1:1', parent: page });
  figma = {
    root, currentPage: page,
    createFrame() {
      const node = makeNode({ name: 'Frame', parent: figma.currentPage,
        width: 100, height: 100, x: 0, y: 0 });
      recordWrite(['createFrame']);
      return node;
    },
    async getNodeByIdAsync(id) {
      calls.push(['getNodeByIdAsync', id]);
      if (hooks.lookup) await hooks.lookup(id);
      return nodes.get(id) || null;
    },
    base64Encode(bytes) {
      calls.push(['base64Encode', bytes.byteLength]);
      return Buffer.from(bytes).toString('base64');
    },
  };
  const params = (extra = {}) => ({
    expected_plugin_instance: instanceId,
    page_id: page.id,
    document_marker: markerValue || null,
    deadline_ms: clock + 10_000,
    ...extra,
  });
  return {
    api: figma, figma, root, page, otherPage, frame, nodes, hooks, writes, calls,
    instanceId, now: () => clock,
    params, makeNode,
    marker: () => markerValue,
    setMarker: (value) => { markerValue = value; },
    setNow: (value) => { clock = value; },
  };
}

module.exports = { createSyntheticFigma };
