'use strict';

// All evidence in this file is synthetic, not native Figma or persistence proof.
const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { createBlueprintEngine } = require('../plugin/blueprint.js');
const { createSyntheticBlueprintFigma, NOW } = require('./support/synthetic_blueprint_figma.cjs');

const OPERATION = 'synthetic-blueprint-operation';
const OPERATION_TAG = 'dcc_mcp_blueprint_operation';
const RESOURCES_TAG = 'dcc_mcp_blueprint_resources';
const PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jN1sAAAAASUVORK5CYII=';
const REGULAR = { family: 'Inter', style: 'Regular' };
const BOLD = { family: 'Inter', style: 'Bold' };
const BLUE = { r: 0.1, g: 0.3, b: 0.9, a: 0.75 };
function clone(value) { return JSON.parse(JSON.stringify(value)); }
function bounds(width = 280, height = 48) { return { x: 0, y: 0, width, height }; }
function layout(mode = 'VERTICAL') {
  return { mode, item_spacing: 12, padding: [16, 16, 16, 16], primary_axis_sizing: 'FIXED',
    counter_axis_sizing: 'FIXED', primary_axis_align: 'MIN', counter_axis_align: 'CENTER' };
}
function node(key, type, extra = {}) {
  return { key, type, name: key, bounds: bounds(), visible: true, opacity: 1, ...extra };
}
function frame(key, children = [], extra = {}) { return node(key, 'FRAME', { children, ...extra }); }
function text(key, characters = 'Sign in', extra = {}) {
  return node(key, 'TEXT', { characters, font: clone(REGULAR), font_size: 16, line_height: 24,
    align: 'left', textAutoResize: 'HEIGHT', fill: { r: 1, g: 1, b: 1, a: 1 }, ...extra });
}
function component(key, children, extra = {}) {
  return node(key, 'COMPONENT', { children, component_set_ref: null, variant_properties: {}, ...extra });
}
function instance(key, reference, overrides = [], extra = {}) {
  return node(key, 'INSTANCE', { component_ref: reference, overrides, ...extra });
}
function minimalBlueprint(trees = [frame('screen')]) {
  return { schema_version: 1, title: 'Synthetic editable login', assets: [],
    variables: { collection: { key: 'tokens', name: 'Synthetic login tokens', mode_key: 'tokens.default', mode_name: 'Default' }, items: [] },
    component_sets: [], node_trees: trees };
}
function richBlueprint() {
  const regular = component('button.default', [text('button.default.label', 'Sign in', {
    layoutSizingHorizontal: 'FILL', layoutSizingVertical: 'HUG',
  })], { auto_layout: layout('HORIZONTAL'), fill: clone(BLUE), corner_radius: 8,
    variable_bindings: { fill: 'color.brand', cornerRadius: 'radius.control' },
    component_set_ref: 'button.states', variant_properties: { state: 'default' } });
  const loading = component('button.loading', [text('button.loading.label', 'Signing in…')], {
    auto_layout: layout('HORIZONTAL'), fill: clone(BLUE),
    component_set_ref: 'button.states', variant_properties: { state: 'loading' },
  });
  const desktop = frame('screen.desktop.default', [
    text('desktop.heading', 'Welcome back', { font: clone(BOLD), font_size: 28, line_height: 36 }),
    node('desktop.email', 'RECTANGLE', { fill: { r: 1, g: 1, b: 1, a: 1 }, stroke: clone(BLUE), stroke_width: 1,
      variable_bindings: { stroke: 'color.brand' }, corner_radius: 8 }),
    instance('desktop.submit', regular.key, [{ target_key: 'button.default.label', characters: 'Sign in securely' }], {
      layoutSizingHorizontal: 'FILL',
    }),
    node('desktop.photo', 'IMAGE', { asset_ref: 'asset.photo', image_fit: 'CONTAIN', bounds: bounds(64, 64) }),
    node('desktop.icon', 'VECTOR', { bounds: bounds(16, 16), fill: clone(BLUE), stroke: clone(BLUE),
      stroke_width: 2, stroke_cap: 'ROUND', stroke_join: 'BEVEL',
      paths: [{ windingRule: 'NONZERO', data: 'M 0 0 L 16 0 L 16 16 L 0 16 Z' }] }),
    node('desktop.spinner', 'ELLIPSE', { bounds: bounds(16, 16), fill: clone(BLUE) }),
  ], { bounds: bounds(1440, 900), auto_layout: layout(), clip_content: true });
  const mobile = frame('screen.mobile.loading', [
    text('mobile.heading', 'Welcome back', { font: clone(BOLD) }),
    instance('mobile.submit', loading.key, [{ target_key: 'button.loading.label', visible: false }]),
  ], { bounds: bounds(390, 844), auto_layout: layout() });
  const blueprint = minimalBlueprint([desktop, mobile, loading, regular]);
  blueprint.assets.push({ key: 'asset.photo', mime_type: 'image/png', data_base64: PNG,
    sha256: createHash('sha256').update(Buffer.from(PNG, 'base64')).digest('hex'), width: 1, height: 1 });
  blueprint.variables.items.push({ key: 'color.brand', name: 'Brand', type: 'COLOR', value: clone(BLUE) },
    { key: 'radius.control', name: 'Control radius', type: 'FLOAT', value: 8 });
  blueprint.component_sets.push({ key: 'button.states', component_keys: [regular.key, loading.key],
    variant_properties: { state: ['default', 'loading'] } });
  return blueprint;
}
function harness(blueprint = minimalBlueprint(), options) {
  const h = createSyntheticBlueprintFigma(options);
  h.expectFontsFromBlueprint(blueprint);
  h.engine = createBlueprintEngine(h.api, h.dependencies);
  h.blueprint = blueprint;
  h.applyParams = (extra = {}) => h.params({ operation_id: OPERATION, blueprint, ...extra });
  h.readParams = (rootId, extra = {}) => h.params({ operation_id: OPERATION, root_node_id: rootId, ...extra });
  return h;
}

test('synthetic blueprint: component-set variant definitions retain first defaults and unique state/viewport options', async () => {
  const order = [['mobile', 'loading'], ['desktop', 'default'], ['mobile', 'default'],
    ['desktop', 'loading'], ['mobile', 'error'], ['desktop', 'error']];
  const components = order.map(([viewport, state]) => component(`login.${viewport}.${state}`, [], {
    component_set_ref: 'login.states', variant_properties: { state, viewport },
  }));
  const blueprint = minimalBlueprint(components);
  blueprint.component_sets.push({ key: 'login.states', component_keys: components.map(item => item.key),
    variant_properties: { state: ['default', 'error', 'loading'], viewport: ['desktop', 'mobile'] } });
  const h = harness(blueprint);
  const applied = await h.engine.apply(h.context, h.applyParams());
  const group = h.nodes.get(applied.component_sets['login.states']);
  const expected = {
    state: { type: 'VARIANT', defaultValue: 'loading', variantOptions: ['loading', 'default', 'error'] },
    viewport: { type: 'VARIANT', defaultValue: 'mobile', variantOptions: ['mobile', 'desktop'] },
  };
  assert.deepEqual(group.componentPropertyDefinitions, expected);
  const before = h.writes.length;
  const read = await h.engine.read(h.context, h.readParams(applied.run_root_id));
  assert.deepEqual(read.nodes.find(item => item.id === group.id).component_property_definitions, expected);
  assert.equal(h.writes.length, before);
});
async function rejected(action, code) {
  let caught;
  try { await action(); } catch (error) { caught = error; }
  assert.ok(caught, 'Expected the typed operation to reject');
  assert.equal(caught.code || caught.message, code);
  assert.ok(caught.receipt && caught.receipt.schema_version === 1);
  return caught;
}
function invalid(action) {
  assert.throws(action, error => error && (error.code || error.message) === 'invalid_arguments');
}

test('synthetic blueprint: typed native API chain creates editable resources and expanded instances', async () => {
  const h = harness(richBlueprint());
  const plan = h.engine.validate('design.blueprint.apply', h.applyParams());
  const data = await h.engine.apply(h.context, h.applyParams());
  assert.equal(data.receipt.stage, 'complete');
  assert.equal(data.receipt.mutation_attempted, true);
  assert.equal(data.expanded_node_count, plan.expanded);
  assert.equal(data.expanded_node_count, h.nodes.size - 2);
  assert.equal(data.receipt.created_node_ids.length, new Set(data.receipt.created_node_ids).size);
  assert.deepEqual(data.receipt.root_ids, [data.run_root_id]);
  for (const id of data.receipt.created_node_ids) assert.ok(h.nodes.has(id));
  for (const op of ['figma.createFrame', 'figma.createComponent', 'figma.createText', 'figma.createRectangle',
    'figma.createEllipse', 'figma.createVector', 'figma.createImage', 'figma.combineAsVariants',
    'component.createInstance', 'variables.createCollection', 'variables.createVariable',
    'variable.setValueForMode', 'node.setBoundVariable']) assert.ok(h.writes.some(write => write.op === op), op);
  assert.equal(h.collections.size, 1);
  const collection = [...h.collections.values()][0];
  assert.deepEqual(collection.modes, [{ modeId: collection.defaultModeId, name: 'Default' }]);
  assert.equal(h.variables.size, 2);
  assert.ok(h.calls.some(call => call.op === 'variables.setBoundVariableForPaint'));
  const firstWrite = h.calls.findIndex(call => call.op === 'write');
  assert.equal(h.calls.slice(0, firstWrite).filter(call => call.op === 'font.load.complete').length, 2);
  assert.equal(h.writes.filter(write => write.op === 'root.setPluginData').length, 1);
  const master = h.nodes.get(data.nodes['button.default']);
  const submitted = h.nodes.get(data.nodes['desktop.submit']);
  assert.equal(submitted.type, 'INSTANCE');
  assert.equal(submitted.children.length, master.children.length);
  assert.notEqual(submitted.children[0].id, master.children[0].id);
  assert.equal(master.children[0].characters, 'Sign in');
  assert.equal(submitted.children[0].characters, 'Sign in securely');
  assert.equal(h.nodes.get(data.nodes['mobile.submit']).children[0].visible, false);
  assert.equal(master.fills[0].opacity, BLUE.a);
  assert.equal(master.fills[0].boundVariables.color.id, data.variables['color.brand']);
  assert.equal(master.boundVariables.cornerRadius.id, data.variables['radius.control']);
  assert.equal(h.nodes.get(data.nodes['desktop.submit']).layoutSizingHorizontal, 'FILL');
  assert.equal(h.images.size, 1);
  const imageFill = h.nodes.get(data.nodes['desktop.photo']).fills[0];
  assert.equal(imageFill.type, 'IMAGE');
  assert.equal(imageFill.scaleMode, 'FIT');
  assert.deepEqual(Buffer.from(h.images.get(imageFill.imageHash)), Buffer.from(PNG, 'base64'));
  assert.deepEqual(h.nodes.get(data.nodes['desktop.icon']).vectorPaths, h.blueprint.node_trees[0].children[4].paths);
  assert.equal(h.nodes.get(data.nodes['desktop.icon']).strokeCap, 'ROUND');
  assert.equal(h.nodes.get(data.nodes['desktop.icon']).strokeJoin, 'BEVEL');
  assert.equal(master.parent.type, 'COMPONENT_SET');
  assert.deepEqual(master.variantProperties, { state: 'default' });
  assert.ok(h.guards.length >= h.writes.length);
  assert.equal(h.writes.filter(write => write.op === 'node.remove').length, 0);
});

test('synthetic blueprint: complete read returns native text/layout/instances/variables and does no writes', async () => {
  const h = harness(richBlueprint());
  const applied = await h.engine.apply(h.context, h.applyParams());
  const before = h.writes.length;
  const data = await h.engine.read(h.context, h.readParams(applied.run_root_id));
  assert.equal(h.writes.length, before);
  assert.equal(data.receipt.mutation_attempted, false);
  assert.equal(data.truncated, false);
  assert.equal(data.expanded_node_count, applied.expanded_node_count);
  const label = data.nodes.find(item => item.id === applied.nodes['desktop.heading']);
  assert.equal(label.characters, 'Welcome back');
  assert.deepEqual(label.typography.fontName, BOLD);
  assert.equal(label.typography.fontSize, 28);
  const submit = data.nodes.find(item => item.id === applied.nodes['desktop.submit']);
  assert.equal(submit.main_component_id, applied.nodes['button.default']);
  assert.equal(submit.layout.layoutMode, 'HORIZONTAL');
  assert.equal(submit.layout.layoutSizingHorizontal, 'FILL');
  assert.equal(data.collections.length, 1);
  assert.equal(data.variables.length, 2);
  assert.deepEqual(data.component_sets, applied.receipt.component_set_ids);
  assert.ok(h.calls.some(call => call.op === 'instance.getMainComponentAsync'));
  const limited = await h.engine.read(h.context, h.readParams(applied.run_root_id, { limit: 2 }));
  assert.equal(limited.nodes.length, 2);
  assert.equal(limited.truncated, true);
  assert.equal(h.writes.length, before);
});

test('synthetic blueprint: tail schema/reference failures preflight all nodes before any write or font request', async (t) => {
  const cases = [
    ['tail unknown property', bp => { bp.node_trees.at(-1).children.push(node('bad', 'RECTANGLE', { eval: 'forbidden' })); }],
    ['missing component ref', bp => { bp.node_trees.at(-1).children.push(instance('bad', 'missing')); }],
    ['bad override target', bp => { bp.node_trees[0].children[2].overrides[0].target_key = 'not-in-master'; }],
    ['characters override on frame', bp => { bp.node_trees[0].children[2].overrides[0].target_key = 'button.default'; }],
    ['bad variable reference', bp => { bp.node_trees.at(-1).variable_bindings.fill = 'missing'; }],
    ['wrong variable type', bp => { bp.node_trees.at(-1).variable_bindings.fill = 'radius.control'; }],
    ['duplicate logical key', bp => { bp.node_trees.at(-1).children.push(node('desktop.email', 'RECTANGLE')); }],
    ['FILL without parent AutoLayout', bp => { delete bp.node_trees[0].auto_layout; }],
    ['variant mismatch', bp => { bp.node_trees.at(-1).variant_properties.state = 'unknown'; }],
    ['RGBA channel out of bounds', bp => { bp.node_trees.at(-1).fill.a = 1.1; }],
    ['image URL instead of bytes', bp => { bp.assets[0].url = 'https://example.invalid/image.png'; }],
    ['wrong PNG hash', bp => { bp.assets[0].sha256 = '0'.repeat(64); }],
    ['non-PNG image bytes', bp => { bp.assets[0].data_base64 = Buffer.from('not png').toString('base64'); }],
    ['remote SVG path', bp => { bp.node_trees[0].children[4].paths[0].data = 'https://example.invalid/icon.svg'; }],
    ['script in path', bp => { bp.node_trees[0].children[4].paths[0].data = 'M 0 0 eval(1)'; }],
    ['unknown top-level operation list', bp => { bp.operations = []; }],
  ];
  for (const [label, change] of cases) await t.test(label, async () => {
    const bp = richBlueprint(); change(bp);
    const h = harness(bp);
    const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'invalid_arguments');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
    assert.equal(h.calls.filter(call => call.op === 'font.load.start').length, 0);
  });
});

test('synthetic blueprint: JSON cycles and component dependency cycles reject before mutation', async (t) => {
  await t.test('JSON cycle', async () => {
    const bp = minimalBlueprint(); bp.node_trees[0].children.push(bp.node_trees[0]);
    const h = createSyntheticBlueprintFigma();
    const engine = createBlueprintEngine(h.api, h.dependencies);
    const error = await rejected(() => engine.apply(h.context, h.params({ operation_id: OPERATION, blueprint: bp })), 'invalid_arguments');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
  });
  for (const mutual of [false, true]) await t.test(mutual ? 'mutual component cycle' : 'self component cycle', async () => {
    const bp = minimalBlueprint([component('a', [instance('a.child', mutual ? 'b' : 'a')])]);
    if (mutual) bp.node_trees.push(component('b', [instance('b.child', 'a')]));
    const h = harness(bp);
    await rejected(() => h.engine.apply(h.context, h.applyParams()), 'invalid_arguments');
    assert.deepEqual(h.writes, []);
  });
});

test('synthetic blueprint: scalar variable binding ranges fail before font loading or writes', async (t) => {
  const cases = [
    ['strokeWeight', -1], ['strokeWeight', 128.001],
    ['cornerRadius', -1], ['cornerRadius', 4096.001],
    ['width', -1], ['width', 0.001], ['width', 8192.001],
    ['height', -1], ['height', 0.001], ['height', 8192.001],
  ];
  for (const [field, value] of cases) await t.test(`${field}=${value}`, async () => {
    const blueprint = richBlueprint();
    blueprint.variables.items.push({ key: 'scalar.value', name: 'Synthetic scalar', type: 'FLOAT', value });
    blueprint.node_trees.at(-1).children.push(node('tail.scalar', 'RECTANGLE', {
      variable_bindings: { [field]: 'scalar.value' },
    }));
    const h = harness(blueprint);
    const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'invalid_arguments');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
    assert.equal(h.calls.filter(call => call.op === 'font.load.start').length, 0);
  });
});

test('synthetic blueprint: an unused negative FLOAT variable remains valid', async () => {
  const blueprint = richBlueprint();
  blueprint.variables.items.push({ key: 'unused.negative', name: 'Unused negative', type: 'FLOAT', value: -64 });
  const h = harness(blueprint);
  const applied = await h.engine.apply(h.context, h.applyParams());
  const read = await h.engine.read(h.context, h.readParams(applied.run_root_id));
  const variable = read.variables.find(item => item.id === applied.variables['unused.negative']);
  assert.equal(variable.type, 'FLOAT');
  assert.deepEqual(Object.values(variable.values_by_mode), [-64]);
});

test('synthetic blueprint: expanded clones count against the 2048-node budget', () => {
  function budget(count) {
    return minimalBlueprint([component('master', [node('master.child', 'RECTANGLE')]),
      frame('screen', Array.from({ length: count }, (_, index) => instance(`instance.${index}`, 'master')))]);
  }
  const accepted = harness(budget(1022));
  assert.equal(accepted.engine.validate('design.blueprint.apply', accepted.applyParams()).expanded, 2048);
  const rejectedBudget = harness(budget(1023));
  invalid(() => rejectedBudget.engine.validate('design.blueprint.apply', rejectedBudget.applyParams()));
  assert.deepEqual(accepted.writes, []);
  assert.deepEqual(rejectedBudget.writes, []);
});

test('synthetic blueprint: depth 24 includes generated run root and component set wrappers', () => {
  function chain(depth, grouped) {
    let tree = frame(`level.${depth}`);
    for (let index = depth - 1; index >= 1; index -= 1) tree = frame(`level.${index}`, [tree]);
    if (grouped) { tree.type = 'COMPONENT'; tree.component_set_ref = 'set'; tree.variant_properties = { state: 'default' }; }
    const bp = minimalBlueprint([tree]);
    if (grouped) bp.component_sets.push({ key: 'set', component_keys: [tree.key], variant_properties: { state: ['default'] } });
    return bp;
  }
  for (const [depth, grouped, accepted] of [[23, false, true], [24, false, false], [22, true, true], [23, true, false]]) {
    const h = harness(chain(depth, grouped));
    if (accepted) h.engine.validate('design.blueprint.apply', h.applyParams());
    else invalid(() => h.engine.validate('design.blueprint.apply', h.applyParams()));
    assert.deepEqual(h.writes, []);
  }
});

test('synthetic blueprint: forward component references are topologically built before cloning', async () => {
  const bp = minimalBlueprint([frame('screen', [instance('screen.a', 'a')]),
    component('a', [instance('a.b', 'b')]), component('b', [text('b.label')])]);
  const h = harness(bp);
  const data = await h.engine.apply(h.context, h.applyParams());
  const b = h.nodes.get(data.nodes.b);
  const a = h.nodes.get(data.nodes.a);
  assert.equal(a.children[0].type, 'INSTANCE');
  assert.equal(a.children[0].children[0].characters, b.children[0].characters);
  const cloned = h.nodes.get(data.nodes['screen.a']);
  assert.equal(cloned.children[0].children[0].type, 'TEXT');
  assert.equal(data.expanded_node_count, h.nodes.size - 2);
});

test('synthetic blueprint: overrides address nested logical keys even when native names are identical', async () => {
  const bp = minimalBlueprint([component('master', [frame('master.group', [
    text('master.first', 'First', { name: 'Repeated label' }),
    text('master.second', 'Second', { name: 'Repeated label' }),
  ])]), frame('screen', [instance('screen.submit', 'master', [
    { target_key: 'master.second', characters: 'Only this text changes', visible: false },
  ])])]);
  const h = harness(bp);
  const data = await h.engine.apply(h.context, h.applyParams());
  const copied = h.nodes.get(data.nodes['screen.submit']).children[0].children;
  assert.equal(copied[0].characters, 'First');
  assert.equal(copied[0].visible, true);
  assert.equal(copied[1].characters, 'Only this text changes');
  assert.equal(copied[1].visible, false);
  assert.equal(h.nodes.get(data.nodes['master.second']).characters, 'Second');
});

test('synthetic blueprint: font failure and scope changes after font await remain zero-write', async (t) => {
  await t.test('font failure', async () => {
    const h = harness(richBlueprint());
    h.hooks.loadFont = async () => { const error = new Error('synthetic_font_failure'); error.code = 'host_error'; throw error; };
    const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'host_error');
    assert.equal(error.receipt.stage, 'fonts');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
  });
  for (const change of ['page', 'marker', 'root', 'deadline', 'closed']) await t.test(change, async () => {
    const h = harness(richBlueprint());
    h.hooks.loadFont = async () => {
      if (change === 'page') h.api.currentPage = h.otherPage;
      if (change === 'marker') h.setMarker('external-marker');
      if (change === 'root') h.api.root = { ...h.root };
      if (change === 'deadline') h.setNow(NOW + 30_000);
      if (change === 'closed') h.close();
    };
    const code = change === 'deadline' ? 'deadline_exceeded' : change === 'closed' ? 'stale_instance' : 'scope_mismatch';
    const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), code);
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
  });
});

test('synthetic blueprint: mutation failures retain partial IDs and never rollback or replay', async () => {
  const h = harness(richBlueprint());
  let attempts = 0;
  h.hooks.beforeWrite = write => {
    if (write.op === 'node.set' && write.property === 'characters') {
      attempts += 1;
      const error = new Error('synthetic_write_failure'); error.code = 'host_error'; throw error;
    }
  };
  const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'host_error');
  assert.equal(attempts, 1);
  assert.equal(error.receipt.mutation_attempted, true);
  assert.ok(error.receipt.completed_steps > 0);
  assert.equal(error.receipt.root_ids.length, 1);
  assert.ok(error.receipt.created_node_ids.length >= 3);
  for (const id of error.receipt.created_node_ids) assert.ok(h.nodes.has(id));
  assert.equal(error.receipt.collection_ids.length, 1);
  assert.equal(error.receipt.variable_ids.length, 2);
  assert.equal(h.writes.filter(write => write.op === 'node.remove').length, 0);
  const before = h.writes.length;
  h.hooks.beforeWrite = null;
  const replay = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'scope_mismatch');
  assert.equal(replay.receipt.mutation_attempted, false);
  assert.equal(h.writes.length, before);
});

test('synthetic blueprint: returned native IDs survive scope loss immediately after creation', async () => {
  const h = harness();
  h.hooks.afterWrite = write => {
    if (write.op === 'variables.createCollection') h.api.currentPage = h.otherPage;
  };
  const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'scope_mismatch');
  assert.equal(error.receipt.mutation_attempted, true);
  assert.equal(error.receipt.collection_ids.length, 1);
  assert.ok(h.collections.has(error.receipt.collection_ids[0]));
  assert.equal(error.receipt.root_ids.length, 1);
  assert.ok(h.nodes.has(error.receipt.root_ids[0]));
  assert.equal(h.writes.at(-1).op, 'variables.createCollection');
  assert.equal(h.writes.filter(write => write.op === 'node.remove').length, 0);
});

test('synthetic blueprint: a returned run-root ID is preserved before its post-create scope check', async () => {
  const h = harness();
  h.hooks.afterWrite = write => { if (write.op === 'figma.createFrame') h.api.currentPage = h.otherPage; };
  const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'scope_mismatch');
  assert.equal(error.receipt.root_ids.length, 1);
  assert.deepEqual(error.receipt.created_node_ids, error.receipt.root_ids);
  assert.ok(h.nodes.has(error.receipt.root_ids[0]));
  assert.equal(h.writes.at(-1).op, 'figma.createFrame');
  assert.equal(h.writes.filter(write => write.op === 'node.remove').length, 0);
});

test('synthetic blueprint: the tagged completed operation cannot be applied twice', async () => {
  const h = harness();
  await h.engine.apply(h.context, h.applyParams());
  const writes = h.writes.length;
  const fontRequests = h.calls.filter(call => call.op === 'font.load.start').length;
  await rejected(() => h.engine.apply(h.context, h.applyParams()), 'scope_mismatch');
  assert.equal(h.writes.length, writes);
  assert.equal(h.calls.filter(call => call.op === 'font.load.start').length, fontRequests);
});

test('synthetic blueprint: read rejects mismatched tags and rechecks scope after async native reads', async (t) => {
  for (const change of ['wrong-tag', 'lookup-page', 'instance-marker', 'variable-marker', 'final-tag']) await t.test(change, async () => {
    const h = harness(richBlueprint());
    const applied = await h.engine.apply(h.context, h.applyParams());
    const runRoot = h.nodes.get(applied.run_root_id);
    const before = h.writes.length;
    if (change === 'wrong-tag') h.inspect(runRoot).pluginData.set(OPERATION_TAG, 'different-operation');
    if (change === 'lookup-page') h.hooks.lookup = async () => { h.api.currentPage = h.otherPage; };
    if (change === 'instance-marker') h.hooks.mainComponent = async () => { h.setMarker('changed-marker'); };
    if (change === 'variable-marker') h.hooks.getVariable = async () => { h.setMarker('changed-marker'); };
    if (change === 'final-tag') h.hooks.getVariable = async () => { h.inspect(runRoot).pluginData.set(OPERATION_TAG, 'different-operation'); };
    const error = await rejected(() => h.engine.read(h.context, h.readParams(applied.run_root_id)), 'scope_mismatch');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.equal(h.writes.length, before);
  });
});

test('synthetic blueprint: malformed persisted resource manifest fails read without changing marker', async () => {
  const h = harness();
  const applied = await h.engine.apply(h.context, h.applyParams());
  const root = h.nodes.get(applied.run_root_id);
  h.inspect(root).pluginData.set(RESOURCES_TAG, '{bad json');
  const before = h.writes.length;
  await rejected(() => h.engine.read(h.context, h.readParams(applied.run_root_id)), 'host_error');
  assert.equal(h.writes.length, before);
});

test('synthetic blueprint: reading a pre-existing tagged root never marks an unmarked document', async () => {
  const h = harness();
  const root = h.seedNode('FRAME');
  h.inspect(root).pluginData.set(OPERATION_TAG, OPERATION);
  h.inspect(root).pluginData.set(RESOURCES_TAG, JSON.stringify({ schema_version: 1, operation_id: OPERATION,
    collection_ids: [], variable_ids: [], component_set_ids: [] }));
  assert.equal(h.context.marker, null);
  const data = await h.engine.read(h.context, h.readParams(root.id));
  assert.equal(data.nodes.length, 1);
  assert.equal(data.receipt.mutation_attempted, false);
  assert.equal(h.context.marker, null);
  assert.equal(h.root.getPluginData('dcc_mcp_document_id'), '');
  assert.deepEqual(h.writes, []);
});

test('synthetic blueprint: read limits retain only the child frontier that fits remaining node slots', async () => {
  const h = harness();
  const root = h.seedNode('FRAME');
  h.inspect(root).pluginData.set(OPERATION_TAG, OPERATION);
  h.inspect(root).pluginData.set(RESOURCES_TAG, JSON.stringify({ schema_version: 1, operation_id: OPERATION,
    collection_ids: [], variable_ids: [], component_set_ids: [] }));
  for (let index = 0; index < 40; index += 1) {
    const child = h.seedNode('FRAME', { parent: root });
    for (let grandchild = 0; grandchild < 10; grandchild += 1) h.seedNode('RECTANGLE', { parent: child });
  }
  const limit = 5;
  const data = await h.engine.read(h.context, h.readParams(root.id, { limit }));
  assert.equal(data.nodes.length, limit);
  assert.equal(data.truncated, true);
  assert.equal(data.nodes[0].child_ids_truncated, true);
  assert.equal(data.nodes[0].child_ids.length, limit - 1);
  assert.deepEqual(data.nodes[0].child_ids, root.children.slice(0, limit - 1).map(child => child.id));
  const emitted = new Set(data.nodes.map(item => item.id));
  let frontier = 0;
  for (let index = 0; index < data.nodes.length; index += 1) {
    const item = data.nodes[index];
    if (index > 0) frontier -= 1;
    const children = item.child_ids || [];
    assert.ok(children.length + frontier <= limit - index - 1, 'Child IDs and pending siblings fit the remaining limit');
    for (const id of children) assert.ok(emitted.has(id), 'Every retained child fits the emitted node budget');
    frontier += children.length;
    if (index > 0) {
      assert.deepEqual(children, []);
      assert.equal(item.child_ids_truncated, true);
    }
  }
  assert.equal(frontier, 0);
  assert.deepEqual(h.writes, []);
});

test('synthetic blueprint: resource manifest bytes are rechecked after native awaits even when its parsed value is unchanged', async (t) => {
  for (const operation of ['mainComponent', 'getVariable']) await t.test(operation, async () => {
    const h = harness(richBlueprint());
    const applied = await h.engine.apply(h.context, h.applyParams());
    const root = h.nodes.get(applied.run_root_id);
    const before = h.writes.length;
    const previous = root.getPluginData(RESOURCES_TAG);
    const marker = h.root.getPluginData('dcc_mcp_document_id');
    h.hooks[operation] = async () => { h.inspect(root).pluginData.set(RESOURCES_TAG, previous + ' '); };
    const error = await rejected(() => h.engine.read(h.context, h.readParams(root.id)), 'scope_mismatch');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.equal(root.getPluginData(OPERATION_TAG), OPERATION);
    assert.equal(h.root.getPluginData('dcc_mcp_document_id'), marker);
    assert.deepEqual(JSON.parse(root.getPluginData(RESOURCES_TAG)), JSON.parse(previous));
    assert.equal(h.writes.length, before);
  });
});

test('synthetic blueprint: persisted resource count and native ID type limits reject before resource lookups', async (t) => {
  const cases = [
    ['two collections', resources => { resources.collection_ids = ['collection:1', 'collection:2']; }],
    ['65 variables', resources => { resources.variable_ids = Array.from({ length: 65 }, (_, index) => `variable:${index}`); }],
    ['33 component sets', resources => { resources.component_set_ids = Array.from({ length: 33 }, (_, index) => `set:${index}`); }],
    ['non-array variable IDs', resources => { resources.variable_ids = {}; }],
    ['non-string variable ID', resources => { resources.variable_ids = [12]; }],
    ['overlong native ID', resources => { resources.variable_ids = ['x'.repeat(129)]; }],
    ['path-like native ID', resources => { resources.variable_ids = ['../external']; }],
    ['duplicate native IDs', resources => { resources.variable_ids = ['variable:1', 'variable:1']; }],
  ];
  for (const [label, change] of cases) await t.test(label, async () => {
    const h = harness();
    const root = h.seedNode('FRAME');
    const resources = { schema_version: 1, operation_id: OPERATION,
      collection_ids: [], variable_ids: [], component_set_ids: [] };
    change(resources);
    h.inspect(root).pluginData.set(OPERATION_TAG, OPERATION);
    h.inspect(root).pluginData.set(RESOURCES_TAG, JSON.stringify(resources));
    const error = await rejected(() => h.engine.read(h.context, h.readParams(root.id)), 'host_error');
    assert.equal(error.receipt.mutation_attempted, false);
    assert.deepEqual(h.writes, []);
    assert.equal(h.calls.filter(call => ['variables.getCollection', 'variables.getVariable'].includes(call.op)).length, 0);
  });
});

test('synthetic blueprint: reserved-looking literal names and text remain editable data through apply and read', async () => {
  const literals = ['constructor', 'prototype', '__proto__'];
  const bp = minimalBlueprint([frame('literal.screen', literals.map((characters, index) =>
    text(`literal.text.${index}`, characters)), { name: 'prototype' })]);
  const h = harness(bp);
  const applied = await h.engine.apply(h.context, h.applyParams());
  assert.equal(applied.receipt.stage, 'complete');
  assert.equal(h.nodes.get(applied.nodes['literal.screen']).name, 'prototype');
  for (let index = 0; index < literals.length; index += 1) {
    assert.equal(h.nodes.get(applied.nodes[`literal.text.${index}`]).characters, literals[index]);
  }
  const before = h.writes.length;
  const data = await h.engine.read(h.context, h.readParams(applied.run_root_id));
  assert.equal(data.nodes.find(item => item.id === applied.nodes['literal.screen']).name, 'prototype');
  for (let index = 0; index < literals.length; index += 1) {
    assert.equal(data.nodes.find(item => item.id === applied.nodes[`literal.text.${index}`]).characters, literals[index]);
  }
  assert.equal(h.writes.length, before);
});

test('synthetic blueprint: an own reserved object property still rejects in zero-write preflight', async () => {
  const bp = minimalBlueprint([frame('safe.screen', [text('safe.copy', 'Ordinary text')])]);
  bp.node_trees[0].bounds = JSON.parse('{"x":0,"y":0,"width":280,"height":48,"__proto__":{"polluted":true}}');
  assert.equal(Object.hasOwn(bp.node_trees[0].bounds, '__proto__'), true);
  const h = harness(bp);
  const error = await rejected(() => h.engine.apply(h.context, h.applyParams()), 'invalid_arguments');
  assert.equal(error.receipt.mutation_attempted, false);
  assert.deepEqual(h.writes, []);
  assert.equal(h.calls.filter(call => call.op === 'font.load.start').length, 0);
  assert.equal(Object.prototype.polluted, undefined);
});

module.exports = { minimalBlueprint, richBlueprint };
