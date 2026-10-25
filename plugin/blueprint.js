/* Bounded, create-only Figma Plugin API blueprint compiler. */
"use strict";

function createBlueprintEngine(figmaApi, dependencies) {
  const { scope, guardedAwait, ensureMarker, boundNode, lookup, snapshot, fail } = dependencies;
  const common = ["expected_plugin_instance", "page_id", "document_marker", "deadline_ms"];
  const operationTag = "dcc_mcp_blueprint_operation";
  const resourcesTag = "dcc_mcp_blueprint_resources";
  const maxNodes = 2048;
  const maxDepth = 24;
  const maxBytes = 2 * 1024 * 1024;
  const keyPattern = /^[A-Za-z0-9/_:.-]{1,200}$/;
  const nativeIdPattern = /^[A-Za-z0-9_:;.-]{1,128}$/;
  const forbidden = new Set(["__proto__", "constructor", "prototype"]);
  const nodeTypes = ["FRAME", "COMPONENT", "TEXT", "INSTANCE", "RECTANGLE", "ELLIPSE", "VECTOR", "IMAGE"];
  const containerTypes = ["FRAME", "COMPONENT"];
  const commonNodeFields = ["key", "type", "name", "bounds", "visible", "opacity", "fill", "stroke",
    "stroke_width", "corner_radius", "variable_bindings", "auto_layout", "layoutSizingHorizontal",
    "layoutSizingVertical", "layout_positioning", "constraints", "clip_content", "stroke_cap", "stroke_join"];

  function invalid() { fail("invalid_arguments"); }
  function own(value, key) { return Object.prototype.hasOwnProperty.call(value, key); }
  function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
  function fields(value, required, optional) {
    if (!object(value)) invalid();
    const allowed = new Set(required.concat(optional || []));
    if (required.some(key => !own(value, key)) || Object.keys(value).some(key => !allowed.has(key) || forbidden.has(key))) invalid();
  }
  function string(value, maximum, empty) {
    return typeof value === "string" && value.length <= maximum && (empty || value.trim().length > 0);
  }
  function key(value) { return typeof value === "string" && keyPattern.test(value) && !forbidden.has(value); }
  function operation(value) { return typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value) && !forbidden.has(value); }
  function finite(value, minimum, maximum) { return typeof value === "number" && Number.isFinite(value) && value >= minimum && value <= maximum; }
  function choice(value, values) { return values.includes(value); }
  function utf8Length(value) {
    let size = 0;
    for (const character of value) {
      const code = character.codePointAt(0);
      size += code < 128 ? 1 : code < 2048 ? 2 : code < 65536 ? 3 : 4;
    }
    return size;
  }
  function jsonBudget(value) {
    const seen = new Set();
    let entries = 0;
    function visit(item, depth) {
      if (++entries > 100000 || depth > 128) invalid();
      if (item === null || typeof item === "boolean") return;
      if (typeof item === "number") { if (!Number.isFinite(item)) invalid(); return; }
      if (typeof item === "string") return;
      if (typeof item !== "object" || seen.has(item)) invalid();
      seen.add(item);
      for (const name of Object.keys(item)) {
        if (forbidden.has(name)) invalid();
        visit(item[name], depth + 1);
      }
      seen.delete(item);
    }
    visit(value, 0);
    if (utf8Length(JSON.stringify(value)) > maxBytes) invalid();
  }
  function rgba(value) {
    fields(value, ["r", "g", "b", "a"], []);
    if (!["r", "g", "b", "a"].every(name => finite(value[name], 0, 1))) invalid();
  }
  function decodeBase64(value) {
    if (!string(value, 1400000, false) || value.length % 4 !== 0 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value)) invalid();
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const output = new Uint8Array(value.length / 4 * 3 - (value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0));
    let offset = 0;
    for (let index = 0; index < value.length; index += 4) {
      const a = alphabet.indexOf(value[index]);
      const b = alphabet.indexOf(value[index + 1]);
      const c = value[index + 2] === "=" ? 0 : alphabet.indexOf(value[index + 2]);
      const d = value[index + 3] === "=" ? 0 : alphabet.indexOf(value[index + 3]);
      if (value[index + 2] === "=" && (b & 15) || value[index + 3] === "=" && value[index + 2] !== "=" && (c & 3)) invalid();
      const group = a << 18 | b << 12 | c << 6 | d;
      if (offset < output.length) output[offset++] = group >>> 16;
      if (offset < output.length) output[offset++] = group >>> 8 & 255;
      if (offset < output.length) output[offset++] = group & 255;
    }
    return output;
  }
  function png(bytes, width, height) {
    if (bytes.length < 45 || ![137, 80, 78, 71, 13, 10, 26, 10].every((value, index) => bytes[index] === value)) invalid();
    const number = index => (bytes[index] * 16777216 + (bytes[index + 1] << 16) + (bytes[index + 2] << 8) + bytes[index + 3]) >>> 0;
    if (number(8) !== 13 || String.fromCharCode(...bytes.slice(12, 16)) !== "IHDR" || number(16) !== width || number(20) !== height) invalid();
    let offset = 8;
    let imageData = false;
    let ended = false;
    while (offset + 12 <= bytes.length) {
      const length = number(offset);
      if (length > bytes.length - offset - 12) invalid();
      const type = String.fromCharCode(...bytes.slice(offset + 4, offset + 8));
      if (!/^[A-Za-z]{4}$/.test(type)) invalid();
      if (type === "IDAT") imageData = true;
      offset += length + 12;
      if (type === "IEND") { if (length !== 0 || offset !== bytes.length) invalid(); ended = true; break; }
    }
    if (!imageData || !ended) invalid();
  }
  function sha256(bytes) {
    const constants = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
      0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
      0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
      0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
      0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
      0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
      0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
      0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    const hash = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    const data = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64);
    data.set(bytes); data[bytes.length] = 128;
    const bitLength = bytes.length * 8;
    for (let index = 0; index < 8; index += 1) data[data.length - 1 - index] = Math.floor(bitLength / 2 ** (8 * index)) & 255;
    const rotate = (value, bits) => value >>> bits | value << 32 - bits;
    for (let offset = 0; offset < data.length; offset += 64) {
      const words = new Uint32Array(64);
      for (let index = 0; index < 16; index += 1) words[index] = data[offset + index * 4] << 24 | data[offset + index * 4 + 1] << 16 | data[offset + index * 4 + 2] << 8 | data[offset + index * 4 + 3];
      for (let index = 16; index < 64; index += 1) {
        const a = words[index - 15]; const b = words[index - 2];
        words[index] = words[index - 16] + (rotate(a,7) ^ rotate(a,18) ^ a >>> 3) + words[index - 7] + (rotate(b,17) ^ rotate(b,19) ^ b >>> 10);
      }
      let [a,b,c,d,e,f,g,h] = hash;
      for (let index = 0; index < 64; index += 1) {
        const first = h + (rotate(e,6) ^ rotate(e,11) ^ rotate(e,25)) + (e & f ^ ~e & g) + constants[index] + words[index];
        const second = (rotate(a,2) ^ rotate(a,13) ^ rotate(a,22)) + (a & b ^ a & c ^ b & c);
        h=g;g=f;f=e;e=d+first|0;d=c;c=b;b=a;a=first+second|0;
      }
      [a,b,c,d,e,f,g,h].forEach((value,index) => { hash[index] = hash[index] + value | 0; });
    }
    return hash.map(value => (value >>> 0).toString(16).padStart(8,"0")).join("");
  }
  function path(value) {
    fields(value, ["windingRule", "data"], []);
    if (!choice(value.windingRule, ["NONZERO", "EVENODD"]) || !string(value.data, 128 * 1024, false)) invalid();
    const tokens = value.data.trim().split(/\s+/);
    const arities = { M: 2, L: 2, Q: 4, C: 6, Z: 0 };
    if (tokens[0] !== "M") invalid();
    for (let index = 0; index < tokens.length;) {
      const command = tokens[index++];
      if (!own(arities, command) || index + arities[command] > tokens.length) invalid();
      for (let count = 0; count < arities[command]; count += 1) {
        const token = tokens[index++];
        if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(token) || !finite(Number(token), -1000000, 1000000)) invalid();
      }
    }
  }
  function layout(value) {
    fields(value, ["mode", "item_spacing", "padding", "primary_axis_sizing", "counter_axis_sizing", "primary_axis_align", "counter_axis_align"], []);
    if (!choice(value.mode, ["NONE", "HORIZONTAL", "VERTICAL"]) || !finite(value.item_spacing, 0, 8192) ||
        !Array.isArray(value.padding) || value.padding.length !== 4 || !value.padding.every(number => finite(number, 0, 8192)) ||
        !choice(value.primary_axis_sizing, ["FIXED", "AUTO"]) || !choice(value.counter_axis_sizing, ["FIXED", "AUTO"]) ||
        !choice(value.primary_axis_align, ["MIN", "MAX", "CENTER", "SPACE_BETWEEN"]) ||
        !choice(value.counter_axis_align, ["MIN", "MAX", "CENTER", "BASELINE"])) invalid();
    if (value.mode === "NONE" && (value.primary_axis_sizing !== "FIXED" || value.counter_axis_sizing !== "FIXED")) invalid();
  }
  function receipt(operationId, stage) {
    return { schema_version: 1, operation_id: operationId, stage, mutation_attempted: false, completed_steps: 0,
      created_node_ids: [], collection_ids: [], variable_ids: [], component_set_ids: [], root_ids: [] };
  }
  function validate(method, params) {
    if (!choice(method, ["design.blueprint.apply", "design.blueprint.read"])) fail("unsupported_method");
    fields(params, common.concat(method === "design.blueprint.apply" ? ["operation_id", "blueprint"] : ["operation_id", "root_node_id"]),
      method === "design.blueprint.read" ? ["limit"] : []);
    if (!operation(params.operation_id)) invalid();
    if (!string(params.expected_plugin_instance, 128, false) || !string(params.page_id, 200, false) ||
        !(params.document_marker === null || string(params.document_marker, 128, false)) ||
        !Number.isSafeInteger(params.deadline_ms) || params.deadline_ms <= 0) invalid();
    if (method === "design.blueprint.read") {
      if (!string(params.root_node_id, 128, false) || own(params, "limit") && (!Number.isInteger(params.limit) || params.limit < 1 || params.limit > maxNodes)) invalid();
      return null;
    }
    jsonBudget(params.blueprint);
    // Own the validated plan across font-loading awaits.
    const blueprint = copy(params.blueprint);
    fields(blueprint, ["schema_version", "title", "assets", "variables", "component_sets", "node_trees"], []);
    if (blueprint.schema_version !== 1 || !string(blueprint.title, 120, false) || !Array.isArray(blueprint.assets) || blueprint.assets.length > 16 ||
        !Array.isArray(blueprint.component_sets) || blueprint.component_sets.length > 32 || !Array.isArray(blueprint.node_trees) || blueprint.node_trees.length === 0 || blueprint.node_trees.length > maxNodes) invalid();
    const plan = { blueprint, nodes: new Map(), parents: new Map(), assets: new Map(), variables: new Map(), sets: new Map(), fonts: new Map(), components: [], roots: [], expanded: 1 };
    const allKeys = new Set();
    function reserve(value) { if (!key(value) || allKeys.has(value)) invalid(); allKeys.add(value); }
    let imageBytes = 0;
    for (const asset of blueprint.assets) {
      fields(asset, ["key", "mime_type", "data_base64", "sha256", "width", "height"], []);
      reserve(asset.key);
      if (asset.mime_type !== "image/png" || !/^[a-f0-9]{64}$/.test(asset.sha256) ||
          !Number.isInteger(asset.width) || !Number.isInteger(asset.height) || !finite(asset.width, 1, 4096) || !finite(asset.height, 1, 4096)) invalid();
      const bytes = decodeBase64(asset.data_base64);
      imageBytes += bytes.length;
      if (imageBytes > 1024 * 1024) invalid();
      png(bytes, asset.width, asset.height);
      if (sha256(bytes) !== asset.sha256) invalid();
      plan.assets.set(asset.key, { asset, bytes });
    }
    fields(blueprint.variables, ["collection", "items"], []);
    const collection = blueprint.variables.collection;
    fields(collection, ["key", "name", "mode_key", "mode_name"], []);
    reserve(collection.key); reserve(collection.mode_key);
    if (!string(collection.name, 120, false) || collection.mode_name !== "Default" || !Array.isArray(blueprint.variables.items) || blueprint.variables.items.length > 64) invalid();
    for (const variable of blueprint.variables.items) {
      fields(variable, ["key", "name", "type", "value"], []);
      reserve(variable.key);
      if (!string(variable.name, 120, false) || !choice(variable.type, ["COLOR", "FLOAT"])) invalid();
      if (variable.type === "COLOR") rgba(variable.value);
      else if (!finite(variable.value, -1000000, 1000000)) invalid();
      plan.variables.set(variable.key, variable);
    }
    for (const set of blueprint.component_sets) {
      fields(set, ["key", "component_keys", "variant_properties"], []);
      reserve(set.key);
      if (!Array.isArray(set.component_keys) || set.component_keys.length === 0 || set.component_keys.length > 64 || new Set(set.component_keys).size !== set.component_keys.length) invalid();
      fields(set.variant_properties, [], ["state", "viewport"]);
      if (Object.keys(set.variant_properties).length === 0) invalid();
      for (const values of Object.values(set.variant_properties)) {
        if (!Array.isArray(values) || values.length === 0 || values.length > 32 || !values.every(value => typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value) && !forbidden.has(value)) || new Set(values).size !== values.length) invalid();
      }
      plan.sets.set(set.key, set);
    }
    let pathBytes = 0;
    let textBytes = 0;
    function visit(node, parent, depth) {
      if (depth > maxDepth - 1 || plan.nodes.size >= maxNodes) invalid();
      const extra = node && containerTypes.includes(node.type) ? ["children"] : node && node.type === "TEXT" ?
        ["characters", "font", "font_size", "line_height", "align", "textAutoResize"] : node && node.type === "INSTANCE" ?
          ["component_ref", "overrides"] : node && node.type === "VECTOR" ? ["paths"] : node && node.type === "IMAGE" ? ["asset_ref", "image_fit"] : [];
      if (node && node.type === "COMPONENT") extra.push("component_set_ref", "variant_properties");
      fields(node, ["key", "type", "name", "bounds", "visible", "opacity"], commonNodeFields.filter(name => !["key", "type", "name", "bounds", "visible", "opacity"].includes(name)).concat(extra));
      reserve(node.key);
      if (!nodeTypes.includes(node.type) || !string(node.name, 120, false) || typeof node.visible !== "boolean") invalid();
      fields(node.bounds, ["x", "y", "width", "height"], []);
      if (!finite(node.bounds.x, -1000000, 1000000) || !finite(node.bounds.y, -1000000, 1000000) ||
          !finite(node.bounds.width, node.type === "VECTOR" ? 0 : 0.001, 8192) || !finite(node.bounds.height, node.type === "VECTOR" ? 0 : 0.001, 8192)) invalid();
      if (own(node, "opacity") && !finite(node.opacity, 0, 1)) invalid();
      for (const name of ["fill", "stroke"]) if (own(node, name) && node[name] !== null) rgba(node[name]);
      if (own(node, "stroke_width") && !finite(node.stroke_width, 0, 128)) invalid();
      if (own(node, "corner_radius") && !finite(node.corner_radius, 0, 4096)) invalid();
      if (own(node, "stroke_cap") && (node.type !== "VECTOR" || !choice(node.stroke_cap, ["NONE", "ROUND", "SQUARE"]))) invalid();
      if (own(node, "stroke_join") && (node.type !== "VECTOR" || !choice(node.stroke_join, ["MITER", "ROUND", "BEVEL"]))) invalid();
      if (own(node, "corner_radius") && !choice(node.type, ["FRAME", "COMPONENT", "INSTANCE", "RECTANGLE"])) invalid();
      if (own(node, "clip_content") && (typeof node.clip_content !== "boolean" || !choice(node.type, ["FRAME", "COMPONENT", "INSTANCE"]))) invalid();
      if (own(node, "auto_layout")) { if (!choice(node.type, ["FRAME", "COMPONENT", "INSTANCE"])) invalid(); layout(node.auto_layout); }
      for (const name of ["layoutSizingHorizontal", "layoutSizingVertical"]) if (own(node, name) && !choice(node[name], ["FIXED", "HUG", "FILL"])) invalid();
      if (own(node, "layout_positioning") && !choice(node.layout_positioning, ["AUTO", "ABSOLUTE"])) invalid();
      if (own(node, "constraints")) {
        fields(node.constraints, ["horizontal", "vertical"], []);
        if (!["horizontal", "vertical"].every(name => choice(node.constraints[name], ["MIN", "MAX", "CENTER", "STRETCH", "SCALE"]))) invalid();
      }
      if (own(node, "variable_bindings")) {
        fields(node.variable_bindings, [], ["fill", "stroke", "strokeWeight", "cornerRadius", "width", "height"]);
        for (const [field, reference] of Object.entries(node.variable_bindings)) {
          const variable = plan.variables.get(reference);
          const scalarRange = { strokeWeight: [0, 128], cornerRadius: [0, 4096], width: [0.01, 8192], height: [0.01, 8192] }[field];
          if (!variable || variable.type !== (["fill", "stroke"].includes(field) ? "COLOR" : "FLOAT") ||
              ["fill", "stroke"].includes(field) && (!own(node, field) || node[field] === null) ||
              field === "cornerRadius" && !choice(node.type, ["FRAME", "COMPONENT", "INSTANCE", "RECTANGLE"]) ||
              scalarRange && !finite(variable.value, scalarRange[0], scalarRange[1]) ||
              ["width", "height"].includes(field) && node.type === "VECTOR" && node.bounds[field] === 0) invalid();
        }
      }
      if (node.type === "TEXT") {
        if (!["characters", "font", "font_size", "line_height", "align"].every(name => own(node, name))) invalid();
        fields(node.font, ["family", "style"], []);
        if (!string(node.characters, 8192, true) || !string(node.font.family, 100, false) || !string(node.font.style, 100, false) ||
            !finite(node.font_size, 1, 512) || !finite(node.line_height, 1, 1024) || !choice(node.align, ["left", "center", "right"]) ||
            own(node, "textAutoResize") && !choice(node.textAutoResize, ["NONE", "WIDTH_AND_HEIGHT", "HEIGHT"])) invalid();
        textBytes += utf8Length(node.characters);
        if (textBytes > 256 * 1024) invalid();
        plan.fonts.set(JSON.stringify(node.font), node.font);
        if (plan.fonts.size > 16) invalid();
      } else if (node.type === "INSTANCE") {
        if (!own(node, "component_ref") || !key(node.component_ref) || !Array.isArray(node.overrides) || node.overrides.length > 64) invalid();
        const targets = new Set();
        for (const override of node.overrides) {
          fields(override, ["target_key"], ["characters", "visible"]);
          if (!key(override.target_key) || targets.has(override.target_key) || Object.keys(override).length < 2 ||
              own(override, "characters") && !string(override.characters, 8192, true) || own(override, "visible") && typeof override.visible !== "boolean") invalid();
          targets.add(override.target_key);
        }
      } else if (node.type === "VECTOR") {
        if (!Array.isArray(node.paths) || node.paths.length === 0 || node.paths.length > 128) invalid();
        for (const item of node.paths) { path(item); pathBytes += utf8Length(item.data); }
        if (pathBytes > 256 * 1024) invalid();
      } else if (node.type === "IMAGE") {
        if (!plan.assets.has(node.asset_ref) || node.image_fit !== "CONTAIN" || own(node, "fill")) invalid();
      }
      if (node.type === "COMPONENT" && parent !== null) invalid();
      if (node.type === "COMPONENT") {
        if (!own(node, "component_set_ref") || !(node.component_set_ref === null || plan.sets.has(node.component_set_ref)) || !object(node.variant_properties)) invalid();
        for (const [name, value] of Object.entries(node.variant_properties)) if (!["state", "viewport"].includes(name) || typeof value !== "string" || !/^[A-Za-z0-9_-]{1,80}$/.test(value)) invalid();
      }
      plan.nodes.set(node.key, node);
      plan.parents.set(node.key, parent);
      if (parent === null) { if (!containerTypes.includes(node.type)) invalid(); plan.roots.push(node); }
      if (containerTypes.includes(node.type)) {
        if (!Array.isArray(node.children)) invalid();
        node.children.forEach(child => visit(child, node, depth + 1));
      }
    }
    blueprint.node_trees.forEach(node => visit(node, null, 1));
    for (const node of plan.nodes.values()) {
      const parent = plan.parents.get(node.key);
      const parentLayout = parent && parent.auto_layout && parent.auto_layout.mode !== "NONE";
      if ((node.layoutSizingHorizontal === "FILL" || node.layoutSizingVertical === "FILL" || node.layout_positioning === "ABSOLUTE") && !parentLayout) invalid();
      for (const name of ["layoutSizingHorizontal", "layoutSizingVertical"]) if (node[name] === "HUG" && node.type !== "TEXT" && !(node.auto_layout && node.auto_layout.mode !== "NONE")) invalid();
      if (node.type === "INSTANCE" && (!plan.nodes.has(node.component_ref) || plan.nodes.get(node.component_ref).type !== "COMPONENT")) invalid();
    }
    const visiting = new Set();
    const counts = new Map();
    const depths = new Map();
    function expanded(node) {
      if (counts.has(node.key)) return counts.get(node.key);
      if (visiting.has(node.key)) invalid();
      visiting.add(node.key);
      let count = 1;
      let depth = 1;
      if (node.type === "INSTANCE") {
        const component = plan.nodes.get(node.component_ref);
        count = expanded(component);
        depth = depths.get(component.key);
      } else for (const child of node.children || []) {
        count += expanded(child);
        depth = Math.max(depth, 1 + depths.get(child.key));
      }
      if (count > maxNodes || depth > maxDepth - 1) invalid();
      visiting.delete(node.key);
      counts.set(node.key, count); depths.set(node.key, depth);
      if (node.type === "COMPONENT") plan.components.push(node);
      return count;
    }
    for (const root of plan.roots) {
      plan.expanded += expanded(root);
      const wrapperDepth = root.type === "COMPONENT" && root.component_set_ref !== null ? 2 : 1;
      if (depths.get(root.key) + wrapperDepth > maxDepth) invalid();
    }
    plan.expanded += blueprint.component_sets.length;
    if (plan.expanded > maxNodes) invalid();
    function targetPath(component, targetKey, prefix, seen) {
      if (seen.has(component.key)) invalid();
      const visited = new Set(seen); visited.add(component.key);
      for (let index = 0; index < (component.children || []).length; index += 1) {
        const child = component.children[index];
        const indexes = prefix.concat(index);
        if (child.key === targetKey) return { indexes, node: child };
        const nested = child.type === "INSTANCE" ? plan.nodes.get(child.component_ref) : child;
        const result = targetPath(nested, targetKey, indexes, visited);
        if (result) return result;
      }
      return null;
    }
    plan.overridePaths = new Map();
    for (const node of plan.nodes.values()) if (node.type === "INSTANCE") {
      plan.overridePaths.set(node.key, node.overrides.map(override => {
        const target = targetPath(plan.nodes.get(node.component_ref), override.target_key, [], new Set());
        if (!target || own(override, "characters") && target.node.type !== "TEXT") invalid();
        return { override, target };
      }));
    }
    const grouped = new Set();
    for (const set of blueprint.component_sets) {
      const combinations = new Set();
      for (const reference of set.component_keys) {
        const component = plan.nodes.get(reference);
        if (!component || component.type !== "COMPONENT" || component.component_set_ref !== set.key || grouped.has(reference)) invalid();
        const names = Object.keys(set.variant_properties).sort();
        if (Object.keys(component.variant_properties).length !== names.length || names.some(name => !set.variant_properties[name].includes(component.variant_properties[name]))) invalid();
        const combination = names.map(name => component.variant_properties[name]).join("|");
        if (combinations.has(combination)) invalid();
        combinations.add(combination); grouped.add(reference);
      }
    }
    for (const component of plan.components) if (component.component_set_ref !== null && !grouped.has(component.key) || component.component_set_ref === null && Object.keys(component.variant_properties).length !== 0) invalid();
    return plan;
  }

  function nativeId(value) {
    if (!value || typeof value.id !== "string" || !nativeIdPattern.test(value.id) || forbidden.has(value.id)) fail("host_error");
    return value.id;
  }
  function paint(color) { return { type: "SOLID", color: { r: color.r, g: color.g, b: color.b }, opacity: color.a }; }
  function copy(value) { return JSON.parse(JSON.stringify(value)); }
  function readCopy(value) {
    let entries = 0; let stringBytes = 0;
    const seen = new Set();
    function visit(item, depth) {
      if (++entries > 4096 || depth > 8) fail("host_error");
      if (item === null || typeof item === "boolean") return item;
      if (typeof item === "number") { if (!Number.isFinite(item)) fail("host_error"); return item; }
      if (typeof item === "string") {
        stringBytes += utf8Length(item);
        if (stringBytes > 256 * 1024) fail("host_error");
        return item;
      }
      if (!item || typeof item !== "object" || seen.has(item)) fail("host_error");
      seen.add(item);
      let result;
      if (Array.isArray(item)) {
        if (item.length > 128) fail("host_error");
        result = item.map(child => visit(child, depth + 1));
      } else {
        result = {};
        let keys = 0;
        for (const name in item) if (own(item, name)) {
          if (++keys > 64 || name.length > 200 || forbidden.has(name)) fail("host_error");
          result[name] = visit(item[name], depth + 1);
        }
      }
      seen.delete(item);
      return result;
    }
    return visit(value, 0);
  }
  function attach(error, value) {
    if (error && typeof error === "object") { error.receipt = copy(value); return error; }
    const wrapped = new Error("host_error"); wrapped.receipt = copy(value); return wrapped;
  }
  function mutate(context, progress, stage, action, observe) {
    scope(context);
    progress.stage = stage;
    progress.mutation_attempted = true;
    const result = action();
    if (observe) observe(result);
    scope(context);
    progress.completed_steps += 1;
    return result;
  }
  function rememberNode(context, progress, node) {
    const stack = [node];
    while (stack.length) {
      const item = stack.pop();
      const id = nativeId(item);
      if (progress.created_node_ids.includes(id)) fail("host_error");
      progress.created_node_ids.push(id);
      if (progress.created_node_ids.length > maxNodes) fail("host_error");
      scope(context);
      boundNode(context, item);
      if (item.children) for (let index = item.children.length - 1; index >= 0; index -= 1) stack.push(item.children[index]);
    }
  }
  async function apply(context, params) {
    const progress = receipt(params && params.operation_id, "preflight");
    try {
      const plan = validate("design.blueprint.apply", params);
      scope(context);
      if (figmaApi.editorType !== "figma" || figmaApi.mode !== "default") fail("unsupported_method");
      for (const name of ["createFrame", "createComponent", "createText", "createRectangle", "createEllipse", "createVector", "createImage", "combineAsVariants", "loadFontAsync"]) if (typeof figmaApi[name] !== "function") fail("host_error");
      if (!figmaApi.variables || !["createVariableCollection", "createVariable", "setBoundVariableForPaint"].every(name => typeof figmaApi.variables[name] === "function")) fail("host_error");
      await guardedAwait(context, () => figmaApi.currentPage.loadAsync());
      for (const child of figmaApi.currentPage.children) {
        boundNode(context, child);
        if (child.type === "FRAME" && child.getPluginData(operationTag) === progress.operation_id) fail("scope_mismatch");
      }
      progress.stage = "fonts";
      for (const font of plan.fonts.values()) await guardedAwait(context, () => figmaApi.loadFontAsync(copy(font)));
      scope(context);
      progress.stage = "marker";
      if (context.marker === null) mutate(context, progress, "marker", () => ensureMarker(context));
      else ensureMarker(context);
      const created = new Map();
      const variables = new Map();
      const images = new Map();
      const sets = new Map();
      const runRoot = mutate(context, progress, "nodes", () => figmaApi.createFrame(), node => {
        progress.root_ids.push(nativeId(node)); rememberNode(context, progress, node);
      });
      const setProperty = (node, name, value, stage) => mutate(context, progress, stage || "nodes", () => { boundNode(context, node); node[name] = value; });
      setProperty(runRoot, "name", plan.blueprint.title);
      setProperty(runRoot, "fills", []);
      setProperty(runRoot, "clipsContent", false);
      mutate(context, progress, "nodes", () => { boundNode(context, runRoot); runRoot.setPluginData(operationTag, progress.operation_id); });
      function persistResources(stage) {
        const data = { schema_version: 1, operation_id: progress.operation_id, collection_ids: progress.collection_ids,
          variable_ids: progress.variable_ids, component_set_ids: progress.component_set_ids };
        mutate(context, progress, stage, () => { boundNode(context, runRoot); runRoot.setPluginData(resourcesTag, JSON.stringify(data)); });
      }
      persistResources("variables");
      const collectionSpec = plan.blueprint.variables.collection;
      const collection = mutate(context, progress, "variables", () => figmaApi.variables.createVariableCollection(collectionSpec.name), result => progress.collection_ids.push(nativeId(result)));
      persistResources("variables");
      if (!string(collection.defaultModeId, 128, false) || !Array.isArray(collection.modes) || collection.modes.length !== 1) fail("host_error");
      mutate(context, progress, "variables", () => collection.renameMode(collection.defaultModeId, collectionSpec.mode_name));
      for (const variableSpec of plan.variables.values()) {
        const variable = mutate(context, progress, "variables", () => figmaApi.variables.createVariable(variableSpec.name, collection, variableSpec.type), result => progress.variable_ids.push(nativeId(result)));
        variables.set(variableSpec.key, variable);
        persistResources("variables");
        mutate(context, progress, "variables", () => variable.setValueForMode(collection.defaultModeId, copy(variableSpec.value)));
      }
      for (const [reference, image] of plan.assets) images.set(reference, mutate(context, progress, "nodes", () => figmaApi.createImage(image.bytes)));
      function append(parent, node) {
        mutate(context, progress, "nodes", () => { boundNode(context, parent); boundNode(context, node); parent.appendChild(node); });
      }
      function assign(node, spec, parent) {
        setProperty(node, "name", spec.name);
        setProperty(node, "visible", spec.visible);
        if (own(spec, "opacity")) setProperty(node, "opacity", spec.opacity);
        if (spec.type === "TEXT") setProperty(node, "fontName", copy(spec.font));
        if (spec.type === "VECTOR") setProperty(node, "vectorPaths", copy(spec.paths));
        else mutate(context, progress, "nodes", () => { boundNode(context, node); node.resize(spec.bounds.width, spec.bounds.height); });
        if (spec.type !== "INSTANCE") {
          setProperty(node, "fills", own(spec, "fill") && spec.fill !== null ? [paint(spec.fill)] : []);
          setProperty(node, "strokes", own(spec, "stroke") && spec.stroke !== null ? [paint(spec.stroke)] : []);
        } else {
          if (own(spec, "fill")) setProperty(node, "fills", spec.fill === null ? [] : [paint(spec.fill)]);
          if (own(spec, "stroke")) setProperty(node, "strokes", spec.stroke === null ? [] : [paint(spec.stroke)]);
        }
        if (own(spec, "stroke_width")) setProperty(node, "strokeWeight", spec.stroke_width);
        if (own(spec, "stroke_cap")) setProperty(node, "strokeCap", spec.stroke_cap);
        if (own(spec, "stroke_join")) setProperty(node, "strokeJoin", spec.stroke_join);
        if (own(spec, "corner_radius")) setProperty(node, "cornerRadius", spec.corner_radius);
        if (own(spec, "clip_content")) setProperty(node, "clipsContent", spec.clip_content);
        if (spec.type === "TEXT") {
          setProperty(node, "fontSize", spec.font_size);
          setProperty(node, "lineHeight", { unit: "PIXELS", value: spec.line_height });
          setProperty(node, "characters", spec.characters);
          setProperty(node, "textAlignHorizontal", spec.align.toUpperCase());
          setProperty(node, "textAutoResize", own(spec, "textAutoResize") ? spec.textAutoResize : "NONE");
        }
        if (spec.type === "IMAGE") {
          const image = images.get(spec.asset_ref);
          if (!image || !string(image.hash, 128, false)) fail("host_error");
          setProperty(node, "fills", [{ type: "IMAGE", imageHash: image.hash, scaleMode: "FIT" }]);
        }
        if (spec.auto_layout) {
          const value = spec.auto_layout;
          setProperty(node, "layoutMode", value.mode);
          if (value.mode !== "NONE") {
            for (const [name, content] of Object.entries({ itemSpacing: value.item_spacing, paddingTop: value.padding[0], paddingRight: value.padding[1],
              paddingBottom: value.padding[2], paddingLeft: value.padding[3], primaryAxisSizingMode: value.primary_axis_sizing,
              counterAxisSizingMode: value.counter_axis_sizing, primaryAxisAlignItems: value.primary_axis_align, counterAxisAlignItems: value.counter_axis_align })) setProperty(node, name, content);
          }
        }
        if (parent) append(parent, node);
        if (own(spec, "layout_positioning")) setProperty(node, "layoutPositioning", spec.layout_positioning);
        for (const name of ["layoutSizingHorizontal", "layoutSizingVertical"]) if (own(spec, name)) setProperty(node, name, spec[name]);
        if (spec.constraints) setProperty(node, "constraints", copy(spec.constraints));
        setProperty(node, "x", spec.bounds.x);
        setProperty(node, "y", spec.bounds.y);
        for (const [field, reference] of Object.entries(spec.variable_bindings || {})) {
          const variable = variables.get(reference);
          if (["fill", "stroke"].includes(field)) {
            const property = field === "fill" ? "fills" : "strokes";
            scope(context);
            const paints = node[property];
            if (!Array.isArray(paints) || paints.length !== 1 || paints[0].type !== "SOLID") fail("host_error");
            const bound = figmaApi.variables.setBoundVariableForPaint(paints[0], "color", variable);
            scope(context);
            setProperty(node, property, [bound]);
          } else mutate(context, progress, "nodes", () => { boundNode(context, node); node.setBoundVariable(field, variable); });
        }
      }
      function build(spec, parent) {
        if (created.has(spec.key)) return created.get(spec.key);
        let native;
        const factory = { FRAME: "createFrame", COMPONENT: "createComponent", TEXT: "createText", RECTANGLE: "createRectangle", ELLIPSE: "createEllipse", VECTOR: "createVector", IMAGE: "createRectangle" };
        if (spec.type === "INSTANCE") {
          const component = created.get(spec.component_ref);
          if (!component || component.type !== "COMPONENT") fail("host_error");
          native = mutate(context, progress, "nodes", () => { boundNode(context, component); return component.createInstance(); }, node => rememberNode(context, progress, node));
        } else native = mutate(context, progress, "nodes", () => figmaApi[factory[spec.type]](), node => rememberNode(context, progress, node));
        created.set(spec.key, native);
        assign(native, spec, parent);
        for (const child of spec.children || []) build(child, native);
        if (spec.type === "INSTANCE") for (const { override, target } of plan.overridePaths.get(spec.key)) {
          let descendant = native;
          for (const index of target.indexes) { boundNode(context, descendant); descendant = descendant.children && descendant.children[index]; if (!descendant) fail("host_error"); }
          boundNode(context, descendant);
          if (descendant.type !== target.node.type) fail("host_error");
          if (own(override, "characters")) setProperty(descendant, "characters", override.characters);
          if (own(override, "visible")) setProperty(descendant, "visible", override.visible);
        }
        boundNode(context, native);
        return native;
      }
      for (const component of plan.components) build(component, runRoot);
      let groupY = 0;
      for (const set of plan.blueprint.component_sets) {
        const components = set.component_keys.map(reference => created.get(reference));
        for (let index = 0; index < components.length; index += 1) {
          const spec = plan.nodes.get(set.component_keys[index]);
          setProperty(components[index], "name", Object.keys(set.variant_properties).sort().map(name => name + "=" + spec.variant_properties[name]).join(", "), "variants");
        }
        const componentSet = mutate(context, progress, "variants", () => { boundNode(context, runRoot); return figmaApi.combineAsVariants(components, runRoot); }, node => {
          const id = nativeId(node); if (progress.created_node_ids.includes(id)) fail("host_error");
          progress.created_node_ids.push(id); progress.component_set_ids.push(id);
        });
        sets.set(set.key, componentSet);
        setProperty(componentSet, "name", set.key, "variants");
        let columnX = 0; let rowHeight = 1;
        for (const component of components) {
          setProperty(component, "x", columnX, "variants"); setProperty(component, "y", 0, "variants");
          columnX += component.width + 80; rowHeight = Math.max(rowHeight, component.height);
        }
        mutate(context, progress, "variants", () => { boundNode(context, componentSet); componentSet.resize(columnX, rowHeight); });
        setProperty(componentSet, "x", 0, "variants"); setProperty(componentSet, "y", groupY, "variants");
        groupY += rowHeight + 160; persistResources("variants");
      }
      for (const component of plan.components) if (component.component_set_ref === null) {
        const node = created.get(component.key);
        setProperty(node, "x", 0); setProperty(node, "y", groupY); groupY += node.height + 160;
      }
      let screenIndex = 0;
      for (const root of plan.roots) if (root.type !== "COMPONENT") {
        const node = build(root, runRoot);
        setProperty(node, "x", screenIndex % 3 * 1700);
        setProperty(node, "y", groupY + 240 + Math.floor(screenIndex / 3) * 1400);
        screenIndex += 1;
      }
      if (progress.created_node_ids.length !== plan.expanded) fail("host_error");
      let width = 100; let height = 100;
      for (const child of runRoot.children) { boundNode(context, child); width = Math.max(width, child.x + child.width + 100); height = Math.max(height, child.y + child.height + 100); }
      mutate(context, progress, "nodes", () => { boundNode(context, runRoot); runRoot.resize(width, height); });
      scope(context);
      progress.stage = "complete";
      return { receipt: copy(progress), nodes: Object.fromEntries(Array.from(created, ([reference, node]) => [reference, nativeId(node)])),
        collections: { [collectionSpec.key]: nativeId(collection) }, variables: Object.fromEntries(Array.from(variables, ([reference, item]) => [reference, nativeId(item)])),
        component_sets: Object.fromEntries(Array.from(sets, ([reference, item]) => [reference, nativeId(item)])), roots: [nativeId(runRoot)],
        expanded_node_count: progress.created_node_ids.length, run_root_id: nativeId(runRoot) };
    } catch (error) { throw attach(error, progress); }
  }

  async function read(context, params) {
    const progress = receipt(params && params.operation_id, "read");
    try {
      validate("design.blueprint.read", params);
      await guardedAwait(context, () => figmaApi.currentPage.loadAsync());
      const root = await lookup(context, params.root_node_id);
      boundNode(context, root);
      if (root.type !== "FRAME" || root.getPluginData(operationTag) !== params.operation_id) fail("scope_mismatch");
      let resources;
      const resourceText = root.getPluginData(resourcesTag);
      try {
        if (!string(resourceText, 32768, false)) fail("host_error");
        resources = JSON.parse(resourceText);
        fields(resources, ["schema_version", "operation_id", "collection_ids", "variable_ids", "component_set_ids"], []);
      } catch (_) { fail("host_error"); }
      if (resources.schema_version !== 1 || resources.operation_id !== params.operation_id ||
          !["collection_ids", "variable_ids", "component_set_ids"].every(name => Array.isArray(resources[name]) && resources[name].length <= ({ collection_ids: 1, variable_ids: 64, component_set_ids: 32 })[name] &&
            resources[name].every(id => typeof id === "string" && nativeIdPattern.test(id) && !forbidden.has(id)) && new Set(resources[name]).size === resources[name].length)) fail("host_error");
      function assertRun() {
        boundNode(context, root);
        if (root.getPluginData(operationTag) !== progress.operation_id || root.getPluginData(resourcesTag) !== resourceText) fail("scope_mismatch");
      }
      async function readAwait(action) {
        assertRun();
        const value = await guardedAwait(context, action);
        assertRun();
        return value;
      }
      const limit = own(params, "limit") ? params.limit : maxNodes;
      const nodes = [];
      const stack = [{ node: root, depth: 1 }];
      const seen = new Set();
      let truncated = false;
      let outputBytes = 0;
      while (stack.length && nodes.length < limit) {
        const { node, depth } = stack.pop();
        if (depth > maxDepth || seen.has(nativeId(node))) fail("host_error");
        seen.add(nativeId(node)); boundNode(context, node);
        const item = { ...snapshot(node) };
        if (typeof item.name === "string" && item.name.length > 120) { item.name = item.name.slice(0, 120); item.name_truncated = true; truncated = true; }
        const children = node.children;
        let retainedChildren = [];
        if (children) {
          const available = depth < maxDepth ? Math.max(0, limit - nodes.length - 1 - stack.length) : 0;
          const count = Math.min(children.length, available);
          retainedChildren = children.slice(0, count);
          item.child_ids = retainedChildren.map(child => nativeId(child));
          item.child_ids_truncated = count < children.length;
          if (item.child_ids_truncated) truncated = true;
        }
        if (choice(node.type, ["FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE"])) {
          item.layout = {};
          for (const name of ["layoutMode", "itemSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "primaryAxisSizingMode", "counterAxisSizingMode", "primaryAxisAlignItems", "counterAxisAlignItems", "layoutSizingHorizontal", "layoutSizingVertical", "clipsContent"]) {
            if (["string", "number", "boolean"].includes(typeof node[name])) item.layout[name] = node[name];
          }
        }
        if (node.type === "TEXT") {
          if (typeof node.characters !== "string") fail("host_error");
          item.characters = node.characters.slice(0, 10000); item.has_missing_font = node.hasMissingFont;
          if (item.characters.length !== node.characters.length) { item.characters_truncated = true; truncated = true; }
          item.typography = {};
          for (const name of ["fontName", "fontSize", "lineHeight", "textAlignHorizontal", "textAutoResize"]) if (typeof node[name] !== "symbol" && node[name] !== undefined) item.typography[name] = readCopy(node[name]);
        }
        if (node.type === "INSTANCE") {
          const component = await readAwait(() => node.getMainComponentAsync());
          boundNode(context, node);
          item.main_component_id = component ? nativeId(component) : null;
          item.component_properties = readCopy(node.componentProperties || {});
        }
        if (choice(node.type, ["COMPONENT", "COMPONENT_SET"])) {
          item.variant_properties = readCopy(node.variantProperties || {});
          item.component_property_definitions = readCopy(node.componentPropertyDefinitions || {});
        }
        if (node.type === "VECTOR") item.paths = readCopy(node.vectorPaths);
        for (const name of ["strokeWeight", "cornerRadius", "strokeCap", "strokeJoin", "layoutPositioning", "layoutSizingHorizontal", "layoutSizingVertical", "constraints", "visible", "opacity"]) {
          if (node[name] !== undefined && typeof node[name] !== "symbol") item[name] = readCopy(node[name]);
        }
        for (const name of ["fills", "strokes", "boundVariables"]) if (node[name] && typeof node[name] !== "symbol") item[name] = readCopy(node[name]);
        outputBytes += utf8Length(JSON.stringify(item));
        if (outputBytes > maxBytes - 131072) { truncated = true; break; }
        nodes.push(item); progress.completed_steps += 1;
        for (let index = retainedChildren.length - 1; index >= 0; index -= 1) stack.push({ node: retainedChildren[index], depth: depth + 1 });
      }
      const collections = [];
      const variables = [];
      for (const id of resources.collection_ids) {
        const collection = await readAwait(() => figmaApi.variables.getVariableCollectionByIdAsync(id));
        if (!collection || collection.remote || nativeId(collection) !== id) fail("scope_mismatch");
        const modes = collection.modes;
        if (!Array.isArray(modes) || modes.length > 64 || !Array.isArray(collection.variableIds)) fail("host_error");
        collections.push({ id, name: String(collection.name).slice(0, 120), default_mode_id: collection.defaultModeId,
          modes: modes.map(mode => ({ modeId: mode.modeId, name: String(mode.name).slice(0, 120) })), variable_ids: resources.variable_ids.slice(),
          untracked_variable_count: Math.max(0, collection.variableIds.length - resources.variable_ids.length) });
      }
      for (const id of resources.variable_ids) {
        const variable = await readAwait(() => figmaApi.variables.getVariableByIdAsync(id));
        if (!variable || variable.remote || nativeId(variable) !== id || !resources.collection_ids.includes(variable.variableCollectionId)) fail("scope_mismatch");
        if (!choice(variable.resolvedType, ["COLOR", "FLOAT"]) || !object(variable.valuesByMode) || Object.keys(variable.valuesByMode).length > 64) fail("host_error");
        const values = {};
        for (const [mode, value] of Object.entries(variable.valuesByMode)) {
          if (!nativeIdPattern.test(mode) || forbidden.has(mode)) fail("host_error");
          if (typeof value === "number") { if (!Number.isFinite(value)) fail("host_error"); values[mode] = value; }
          else if (object(value) && value.type === "VARIABLE_ALIAS" && typeof value.id === "string" && nativeIdPattern.test(value.id)) values[mode] = { type: "VARIABLE_ALIAS", id: value.id };
          else {
            const color = object(value) && !own(value, "a") ? { ...value, a: 1 } : value;
            try { rgba(color); } catch (_) { fail("host_error"); }
            values[mode] = copy(color);
          }
        }
        variables.push({ id, name: String(variable.name).slice(0, 120), collection_id: variable.variableCollectionId, type: variable.resolvedType, values_by_mode: values });
      }
      for (const id of resources.component_set_ids) {
        const set = await readAwait(() => lookup(context, id));
        if (set.type !== "COMPONENT_SET") fail("scope_mismatch");
        let ancestor = set; let depth = 0;
        while (ancestor !== root && ancestor && depth++ < maxDepth) ancestor = ancestor.parent;
        if (ancestor !== root) fail("scope_mismatch");
      }
      boundNode(context, root);
      if (root.getPluginData(operationTag) !== params.operation_id || root.getPluginData(resourcesTag) !== resourceText) fail("scope_mismatch");
      const data = { receipt: progress, run_root_id: nativeId(root), nodes, collections, variables, component_sets: resources.component_set_ids.slice(), truncated: truncated || stack.length > 0, expanded_node_count: nodes.length };
      if (utf8Length(JSON.stringify(data)) > maxBytes) fail("host_error");
      scope(context);
      return data;
    } catch (error) { throw attach(error, progress); }
  }
  return { validate, apply, read };
}

if (typeof module !== "undefined" && module.exports) module.exports = { createBlueprintEngine };
