'use strict';

// Synthetic official-API-shaped fixture. No native host or persistence claim.
const assert = require('node:assert/strict');

const INSTANCE_ID = 'synthetic-blueprint-instance';
const NOW = 1_800_000_000_000;
const MARKER = 'dcc_mcp_document_id';

function copy(value) { return value === undefined ? undefined : JSON.parse(JSON.stringify(value)); }
function fontKey(value) { return JSON.stringify({ family: value.family, style: value.style }); }

function createSyntheticBlueprintFigma({ instanceId = INSTANCE_ID, now = NOW, marker = null,
  enforceFixtureGuards = true } = {}) {
  const writes = [];
  const calls = [];
  const guards = [];
  const nodes = new Map();
  const nodeState = new WeakMap();
  const collections = new Map();
  const variables = new Map();
  const images = new Map();
  const loadedFonts = new Set();
  const requiredFonts = new Set();
  const hooks = { loadPage: null, loadFont: null, lookup: null, mainComponent: null,
    getCollection: null, getVariable: null, beforeWrite: null, afterWrite: null, scope: null, export: null };
  let clock = now;
  let active = true;
  let markerValue = marker;
  let serial = 10;
  let guardReady = false;
  let api;

  function fail(code) { const error = new Error(code); error.code = code; throw error; }
  function performWrite(op, details, action) {
    if (enforceFixtureGuards) assert.equal(guardReady, true, `Synthetic write ${op} requires a fresh scope guard`);
    for (const key of requiredFonts) assert.ok(loadedFonts.has(key), `Font not loaded before ${op}: ${key}`);
    guardReady = false;
    const entry = { op, ...details };
    if (hooks.beforeWrite) hooks.beforeWrite(entry);
    const result = action();
    writes.push(entry);
    calls.push({ op: 'write', write: entry });
    if (hooks.afterWrite) hooks.afterWrite(entry, result);
    return result;
  }
  const root = {
    id: '0:0', type: 'DOCUMENT', name: 'Synthetic blueprint document', children: [], removed: false,
    getPluginData(key) { assert.equal(key, MARKER); return markerValue || ''; },
    setPluginData(key, value) {
      assert.equal(key, MARKER);
      return performWrite('root.setPluginData', { key, value }, () => { markerValue = value; });
    },
  };
  function makePage(id, name) {
    const page = { id, type: 'PAGE', name, parent: root, children: [], removed: false,
      async loadAsync() {
        calls.push({ op: 'page.loadAsync', id });
        if (hooks.loadPage) await hooks.loadPage(page);
      } };
    root.children.push(page); nodes.set(id, page);
    return page;
  }
  const page = makePage('0:1', 'Synthetic blueprint page');
  const otherPage = makePage('0:2', 'Other synthetic page');

  function detach(node) {
    const state = nodeState.get(node);
    const parent = state.parent;
    if (parent) {
      const children = nodeState.has(parent) ? nodeState.get(parent).children : parent.children;
      const index = children.indexOf(node);
      if (index !== -1) children.splice(index, 1);
    }
    state.parent = null;
  }
  function attach(parent, node) {
    detach(node);
    nodeState.get(node).parent = parent;
    (nodeState.has(parent) ? nodeState.get(parent).children : parent.children).push(node);
  }
  function requireFont(node, font) {
    assert.ok(loadedFonts.has(fontKey(font || node.fontName)), 'Text mutation requires its exact loaded font');
  }
  const containerTypes = new Set(['FRAME', 'COMPONENT', 'COMPONENT_SET', 'INSTANCE']);
  function makeNode(type, { parent = api.currentPage, values = {}, mainComponent = null } = {}) {
    const state = { id: `1:${serial++}`, type, parent: null, children: [], removed: false,
      pluginData: new Map(), mainComponent,
      values: { name: type, visible: true, opacity: 1, x: 0, y: 0, width: 100, height: 100,
        fills: [], strokes: [], strokeWeight: 1, strokeCap: 'NONE', strokeJoin: 'MITER', cornerRadius: 0, clipsContent: false,
        layoutMode: 'NONE', itemSpacing: 0, paddingTop: 0, paddingRight: 0, paddingBottom: 0, paddingLeft: 0,
        primaryAxisSizingMode: 'FIXED', counterAxisSizingMode: 'FIXED', primaryAxisAlignItems: 'MIN',
        counterAxisAlignItems: 'MIN', layoutSizingHorizontal: 'FIXED', layoutSizingVertical: 'FIXED',
        layoutPositioning: 'AUTO', constraints: { horizontal: 'MIN', vertical: 'MIN' },
        boundVariables: {}, vectorPaths: [], fontName: { family: 'Inter', style: 'Regular' },
        fontSize: 12, lineHeight: { unit: 'PIXELS', value: 16 }, characters: '',
        textAlignHorizontal: 'LEFT', textAutoResize: 'NONE', hasMissingFont: false,
        componentProperties: {}, componentPropertyDefinitions: {}, variantProperties: {}, ...copy(values) } };
    let node;
    const methods = {
      resize(width, height) {
        if (type === 'TEXT') requireFont(node);
        assert.ok(Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0);
        return performWrite('node.resize', { node_id: state.id, width, height }, () => {
          state.values.width = width; state.values.height = height;
        });
      },
      appendChild(child) {
        assert.ok(containerTypes.has(type));
        assert.notEqual(type, 'INSTANCE', 'Instance children are cloned by createInstance, not appended by the compiler');
        assert.ok(nodeState.has(child));
        return performWrite('node.appendChild', { parent_id: state.id, node_id: child.id }, () => attach(node, child));
      },
      getPluginData(key) { return state.pluginData.get(key) || ''; },
      setPluginData(key, value) {
        assert.equal(typeof value, 'string');
        return performWrite('node.setPluginData', { node_id: state.id, key, value }, () => state.pluginData.set(key, value));
      },
      setBoundVariable(field, variable) {
        assert.equal(variable.resolvedType, 'FLOAT');
        return performWrite('node.setBoundVariable', { node_id: state.id, field, variable_id: variable.id }, () => {
          state.values.boundVariables[field] = { type: 'VARIABLE_ALIAS', id: variable.id };
          state.values[field] = variable.valuesByMode[collections.get(variable.variableCollectionId).defaultModeId];
        });
      },
      remove() {
        return performWrite('node.remove', { node_id: state.id }, () => { detach(node); state.removed = true; });
      },
    };
    if (type === 'COMPONENT') methods.createInstance = () => {
      return performWrite('component.createInstance', { component_id: state.id }, () => {
        function clone(source, cloneParent, instanceRoot) {
          const sourceState = nodeState.get(source);
          const cloned = makeNode(instanceRoot ? 'INSTANCE' : source.type, { parent: cloneParent,
            values: sourceState.values, mainComponent: instanceRoot ? node : sourceState.mainComponent });
          nodeState.get(cloned).pluginData = new Map(sourceState.pluginData);
          for (const child of sourceState.children) clone(child, cloned, false);
          return cloned;
        }
        const instance = clone(node, api.currentPage, true);
        const properties = {};
        for (const [name, value] of Object.entries(state.values.variantProperties)) properties[name] = { type: 'VARIANT', value };
        nodeState.get(instance).values.componentProperties = properties;
        return instance;
      });
    };
    if (type === 'INSTANCE') methods.getMainComponentAsync = async () => {
      calls.push({ op: 'instance.getMainComponentAsync', node_id: state.id });
      if (hooks.mainComponent) await hooks.mainComponent(node);
      return state.mainComponent;
    };
    if (type === 'FRAME') methods.exportAsync = async options => {
      assert.ok(options && ['PNG', 'SVG'].includes(options.format));
      calls.push({ op: 'frame.exportAsync', node_id: state.id, options: copy(options) });
      if (hooks.export) return await hooks.export(node, options);
      if (options.format === 'SVG') return new TextEncoder().encode('<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>');
      return new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=', 'base64'));
    };
    node = new Proxy({}, {
      get(_target, property) {
        if (property === 'id' || property === 'type' || property === 'parent' || property === 'removed') return state[property];
        if (property === 'children') return containerTypes.has(type) ? state.children : undefined;
        if (Object.hasOwn(methods, property)) return methods[property];
        return state.values[property];
      },
      set(_target, property, value) {
        assert.ok(Object.hasOwn(state.values, property), `Unsupported synthetic node property: ${String(property)}`);
        if (['layoutSizingHorizontal', 'layoutSizingVertical'].includes(property) && value === 'FILL') {
          assert.ok(state.parent && ['HORIZONTAL', 'VERTICAL'].includes(state.parent.layoutMode), 'FILL requires an AutoLayout parent');
        }
        if (type === 'TEXT' && ['fontName', 'fontSize', 'lineHeight', 'characters', 'textAutoResize'].includes(property)) {
          requireFont(node, property === 'fontName' ? value : undefined);
        }
        performWrite('node.set', { node_id: state.id, property, value: copy(value) }, () => { state.values[property] = copy(value); });
        return true;
      },
    });
    nodeState.set(node, state); nodes.set(state.id, node);
    if (parent) attach(parent, node);
    return node;
  }

  api = { root, currentPage: page, editorType: 'figma', mode: 'default',
    base64Encode(bytes) {
      assert.ok(bytes instanceof Uint8Array);
      calls.push({ op: 'figma.base64Encode', byte_length: bytes.byteLength });
      return Buffer.from(bytes).toString('base64');
    },
    async loadFontAsync(font) {
      calls.push({ op: 'font.load.start', font: copy(font) });
      if (hooks.loadFont) await hooks.loadFont(font);
      loadedFonts.add(fontKey(font));
      calls.push({ op: 'font.load.complete', font: copy(font) });
    },
    async getNodeByIdAsync(id) {
      calls.push({ op: 'node.lookup', id });
      if (hooks.lookup) await hooks.lookup(id);
      return nodes.get(id) || null;
    },
    createImage(bytes) {
      assert.ok(bytes instanceof Uint8Array);
      assert.deepEqual(Array.from(bytes.slice(0, 8)), [137, 80, 78, 71, 13, 10, 26, 10]);
      return performWrite('figma.createImage', { byte_length: bytes.length }, () => {
        const image = { hash: `synthetic-image-${serial++}` };
        images.set(image.hash, new Uint8Array(bytes)); return image;
      });
    },
    combineAsVariants(components, parent) {
      assert.ok(components.length > 0 && components.every(node => node.type === 'COMPONENT'));
      return performWrite('figma.combineAsVariants', { component_ids: components.map(node => node.id), parent_id: parent.id }, () => {
        const group = makeNode('COMPONENT_SET', { parent });
        const definitions = {};
        for (const component of components) {
          attach(group, component);
          const variants = Object.fromEntries(component.name.split(', ').map(pair => pair.split('=')));
          nodeState.get(component).values.variantProperties = variants;
          for (const [name, value] of Object.entries(variants)) {
            if (!Object.hasOwn(definitions, name)) definitions[name] = { type: 'VARIANT', defaultValue: value, variantOptions: [] };
            if (!definitions[name].variantOptions.includes(value)) definitions[name].variantOptions.push(value);
          }
        }
        nodeState.get(group).values.componentPropertyDefinitions = definitions;
        return group;
      });
    },
  };
  for (const [method, type] of Object.entries({ createFrame: 'FRAME', createComponent: 'COMPONENT', createText: 'TEXT',
    createRectangle: 'RECTANGLE', createEllipse: 'ELLIPSE', createVector: 'VECTOR' })) {
    api[method] = () => performWrite(`figma.${method}`, {}, () => makeNode(type));
  }
  api.variables = {
    createVariableCollection(name) {
      return performWrite('variables.createCollection', { name }, () => {
        const id = `VariableCollectionId:${serial++}`;
        const defaultModeId = `mode:${serial++}`;
        const collection = { id, name, defaultModeId, remote: false, modes: [{ modeId: defaultModeId, name: 'Mode 1' }], variableIds: [],
          renameMode(modeId, nextName) {
            assert.equal(modeId, defaultModeId);
            return performWrite('collection.renameMode', { collection_id: id, mode_id: modeId, name: nextName }, () => {
              collection.modes[0].name = nextName;
            });
          } };
        collections.set(id, collection); return collection;
      });
    },
    createVariable(name, collection, resolvedType) {
      assert.equal(collections.get(collection.id), collection, 'Use the official collection-object overload');
      return performWrite('variables.createVariable', { name, collection_id: collection.id, resolvedType }, () => {
        const id = `VariableID:${serial++}`;
        const variable = { id, name, resolvedType, variableCollectionId: collection.id, remote: false, valuesByMode: {},
          setValueForMode(modeId, value) {
            assert.equal(modeId, collection.defaultModeId);
            if (resolvedType === 'FLOAT') assert.equal(typeof value, 'number');
            else assert.ok(['r', 'g', 'b', 'a'].every(field => typeof value[field] === 'number'));
            return performWrite('variable.setValueForMode', { variable_id: id, mode_id: modeId, value: copy(value) }, () => {
              variable.valuesByMode[modeId] = copy(value);
            });
          } };
        collection.variableIds.push(id); variables.set(id, variable); return variable;
      });
    },
    setBoundVariableForPaint(paint, field, variable) {
      assert.equal(field, 'color'); assert.equal(paint.type, 'SOLID'); assert.equal(variable.resolvedType, 'COLOR');
      calls.push({ op: 'variables.setBoundVariableForPaint', variable_id: variable.id });
      return { ...copy(paint), boundVariables: { color: { type: 'VARIABLE_ALIAS', id: variable.id } } };
    },
    async getVariableCollectionByIdAsync(id) {
      calls.push({ op: 'variables.getCollection', id });
      if (hooks.getCollection) await hooks.getCollection(id);
      return collections.get(id) || null;
    },
    async getVariableByIdAsync(id) {
      calls.push({ op: 'variables.getVariable', id });
      if (hooks.getVariable) await hooks.getVariable(id);
      return variables.get(id) || null;
    },
  };
  const context = { marker: markerValue, pageId: page.id, deadline: clock + 30_000 };
  function scope(current) {
    guards.push({ marker: current.marker, page_id: api.currentPage.id, now: clock });
    if (hooks.scope) hooks.scope(current);
    if (!active) fail('stale_instance');
    if (api.root !== root || api.currentPage !== page || page.removed || root.removed || current.pageId !== page.id || current.marker !== markerValue) fail('scope_mismatch');
    if (clock >= current.deadline) fail('deadline_exceeded');
    guardReady = true;
  }
  async function guardedAwait(current, action) { scope(current); const result = await action(); scope(current); return result; }
  function boundNode(current, node) {
    scope(current);
    if (!node || node.removed) fail('node_not_found');
    let ancestor = node;
    for (let depth = 0; ancestor && depth < 1000; depth += 1, ancestor = ancestor.parent) if (ancestor === page) return node;
    fail('scope_mismatch');
  }
  async function lookup(current, id) { return boundNode(current, await guardedAwait(current, () => api.getNodeByIdAsync(id))); }
  function ensureMarker(current) {
    scope(current);
    if (current.marker === null) {
      root.setPluginData(MARKER, instanceId); current.marker = instanceId; scope(current);
    }
  }
  const dependencies = { scope, guardedAwait, ensureMarker, boundNode, lookup, fail,
    info: () => ({ name: root.name, page_id: page.id, page_name: page.name, marker: markerValue }),
    snapshot: node => ({ id: node.id, type: node.type, name: node.name, parent_id: node.parent ? node.parent.id : null,
      x: node.x, y: node.y, width: node.width, height: node.height }) };
  function expectFontsFromBlueprint(blueprint) {
    requiredFonts.clear();
    const visit = node => {
      if (node.type === 'TEXT') requiredFonts.add(fontKey(node.font));
      for (const child of node.children || []) visit(child);
    };
    for (const node of blueprint.node_trees) visit(node);
  }
  return { api, dependencies, context, nodes, writes, calls, guards, hooks, page, otherPage, root,
    collections, variables, images, loadedFonts, requiredFonts, instanceId, expectFontsFromBlueprint,
    params: extra => ({ expected_plugin_instance: instanceId, page_id: page.id, document_marker: markerValue,
      deadline_ms: context.deadline, ...extra }),
    setNow: value => { clock = value; }, setMarker: value => { markerValue = value; },
    close: () => { active = false; }, seedNode: makeNode,
    inspect: node => nodeState.get(node),
  };
}

module.exports = { createSyntheticBlueprintFigma, INSTANCE_ID, NOW, MARKER };
