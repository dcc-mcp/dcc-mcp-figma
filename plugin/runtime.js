/* Typed Figma Plugin API operations. Native acceptance is a separate host test. */
"use strict";

function createFigmaRuntime(figmaApi, options) {
  const markerKey = "dcc_mcp_document_id";
  const maxExportBytes = 1024 * 1024;
  const instanceId = options && options.instanceId;
  const now = options && options.now ? options.now : Date.now;
  const root = figmaApi.root;
  const page = figmaApi.currentPage;
  let active = true;
  let initialized = false;
  let knownMarker = null;

  class RuntimeFailure extends Error {
    constructor(code) {
      super(code);
      this.code = code;
    }
  }

  function fail(code) { throw new RuntimeFailure(code); }
  function own(value, key) { return Object.prototype.hasOwnProperty.call(value, key); }
  function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
  function marker() {
    const value = root.getPluginData(markerKey);
    if (typeof value !== "string") fail("host_error");
    return value === "" ? null : value;
  }
  function info() {
    return { name: root.name, page_id: page.id, page_name: page.name, marker: knownMarker };
  }
  function scope(context) {
    if (!active) fail("stale_instance");
    if (figmaApi.root !== root || figmaApi.currentPage !== page || page.removed || root.removed ||
        page.id !== context.pageId || marker() !== context.marker || knownMarker !== context.marker) {
      fail("scope_mismatch");
    }
    if (context.deadline !== null && now() >= context.deadline) fail("deadline_exceeded");
  }
  async function guardedAwait(context, operation) {
    scope(context);
    const value = await operation();
    scope(context);
    return value;
  }
  function snapshot(node) {
    const number = key => typeof node[key] === "number" && Number.isFinite(node[key]) ? node[key] : null;
    return { id: node.id, type: node.type, name: node.name, x: number("x"), y: number("y"),
      width: number("width"), height: number("height"), parent_id: node.parent ? node.parent.id : null };
  }
  function boundNode(context, node) {
    scope(context);
    if (!node || node.removed) fail("node_not_found");
    let ancestor = node;
    for (let count = 0; ancestor && count < 1000; count += 1) {
      if (ancestor === page) return node;
      ancestor = ancestor.parent;
    }
    fail("scope_mismatch");
  }
  async function lookup(context, nodeId) {
    const node = await guardedAwait(context, () => figmaApi.getNodeByIdAsync(nodeId));
    return boundNode(context, node);
  }
  function fields(params, required, optional) {
    if (!isObject(params)) fail("invalid_arguments");
    const allowed = new Set(required.concat(optional));
    if (required.some(key => !own(params, key)) || Object.keys(params).some(key => !allowed.has(key))) {
      fail("invalid_arguments");
    }
  }
  function text(value, limit) { return typeof value === "string" && value.trim().length > 0 && value.length <= limit; }
  function dimension(value) { return typeof value === "number" && Number.isFinite(value) && value >= 1 && value <= 8192; }
  function coordinate(value) { return typeof value === "number" && Number.isFinite(value) && Math.abs(value) <= 1000000; }
  function frameFields(params) {
    if (own(params, "name") && !text(params.name, 120)) fail("invalid_arguments");
    for (const key of ["width", "height"]) if (own(params, key) && !dimension(params[key])) fail("invalid_arguments");
    for (const key of ["x", "y"]) if (own(params, key) && !coordinate(params[key])) fail("invalid_arguments");
    if (own(params, "fill") && (typeof params.fill !== "string" || !/^#[0-9a-fA-F]{6}$/.test(params.fill))) {
      fail("invalid_arguments");
    }
  }
  function validate(method, params) {
    const common = ["expected_plugin_instance", "page_id", "document_marker", "deadline_ms"];
    const editable = ["name", "width", "height", "x", "y", "fill"];
    if (method === "document.read") fields(params, common, ["limit"]);
    else if (method === "node.read") fields(params, common.concat("node_id"), []);
    else if (method === "frame.create") fields(params, common.concat(editable), []);
    else if (method === "frame.update") {
      fields(params, common.concat("node_id"), editable);
      if (!editable.some(key => own(params, key))) fail("invalid_arguments");
    } else if (method === "node.export") fields(params, common.concat(["node_id", "format"]), []);
    else fail("unsupported_method");
    if (!text(params.expected_plugin_instance, 128) || !text(params.page_id, 200) ||
        !(params.document_marker === null || text(params.document_marker, 128)) ||
        !Number.isSafeInteger(params.deadline_ms) || params.deadline_ms <= 0) fail("invalid_arguments");
    if (own(params, "node_id") && !text(params.node_id, 200)) fail("invalid_arguments");
    if (method === "document.read" && own(params, "limit") &&
        (!Number.isInteger(params.limit) || params.limit < 1 || params.limit > 200)) fail("invalid_arguments");
    if (method === "node.export" && !["PNG", "SVG"].includes(params.format)) fail("invalid_arguments");
    if (method === "frame.create" || method === "frame.update") frameFields(params);
    if (!initialized || params.expected_plugin_instance !== instanceId) fail("stale_instance");
    if (params.page_id !== page.id || params.document_marker !== knownMarker) fail("scope_mismatch");
    const context = { marker: knownMarker, pageId: page.id, deadline: params.deadline_ms };
    scope(context);
    return context;
  }
  function ensureMarker(context) {
    scope(context);
    if (knownMarker === null) {
      root.setPluginData(markerKey, instanceId);
      knownMarker = instanceId;
      context.marker = instanceId;
      scope(context);
    }
  }
  function paint(hex) {
    return [{ type: "SOLID", color: { r: parseInt(hex.slice(1, 3), 16) / 255,
      g: parseInt(hex.slice(3, 5), 16) / 255, b: parseInt(hex.slice(5, 7), 16) / 255 } }];
  }
  function updateFrame(context, node, params) {
    if (own(params, "name")) { boundNode(context, node); node.name = params.name; }
    if (own(params, "width") || own(params, "height")) {
      boundNode(context, node);
      node.resize(own(params, "width") ? params.width : node.width, own(params, "height") ? params.height : node.height);
    }
    for (const key of ["x", "y"]) if (own(params, key)) { boundNode(context, node); node[key] = params[key]; }
    if (own(params, "fill")) { boundNode(context, node); node.fills = paint(params.fill); }
    boundNode(context, node);
    return snapshot(node);
  }
  function errorResult(error) {
    return { ok: false, error: error instanceof RuntimeFailure ? error.code : "host_error" };
  }
  async function initialize() {
    try {
      if (!text(instanceId, 128) || typeof now !== "function") fail("invalid_arguments");
      if (!active) fail("stale_instance");
      knownMarker = marker();
      const context = { marker: knownMarker, pageId: page.id, deadline: null };
      await guardedAwait(context, () => page.loadAsync());
      initialized = true;
      return { ok: true, document: info() };
    } catch (error) { return errorResult(error); }
  }
  async function dispatch(method, params) {
    try {
      const context = validate(method, params);
      await guardedAwait(context, () => page.loadAsync());
      let data;
      if (method === "document.read") {
        scope(context);
        const children = page.children;
        const limit = own(params, "limit") ? params.limit : 100;
        data = { nodes: children.slice(0, limit).map(node => snapshot(boundNode(context, node))), truncated: children.length > limit };
      } else if (method === "node.read") {
        data = snapshot(await lookup(context, params.node_id));
      } else if (method === "frame.create") {
        ensureMarker(context);
        scope(context);
        const node = figmaApi.createFrame();
        boundNode(context, node);
        data = updateFrame(context, node, params);
      } else if (method === "frame.update") {
        const node = await lookup(context, params.node_id);
        if (node.type !== "FRAME") fail("unsupported_node");
        if ((own(params, "width") || own(params, "height")) &&
            (!dimension(own(params, "width") ? params.width : node.width) ||
             !dimension(own(params, "height") ? params.height : node.height))) fail("invalid_arguments");
        ensureMarker(context);
        data = updateFrame(context, node, params);
      } else {
        const node = await lookup(context, params.node_id);
        if (node.type !== "FRAME") fail("unsupported_node");
        const bytes = await guardedAwait(context, () => node.exportAsync({ format: params.format }));
        if (!(bytes instanceof Uint8Array) || bytes.byteLength === 0) fail("host_error");
        if (bytes.byteLength > maxExportBytes) fail("export_too_large");
        boundNode(context, node);
        const encoded = figmaApi.base64Encode(bytes);
        if (typeof encoded !== "string" || !/^[A-Za-z0-9+/]+={0,2}$/.test(encoded)) fail("host_error");
        scope(context);
        data = { node_id: node.id, format: params.format,
          mime_type: params.format === "PNG" ? "image/png" : "image/svg+xml",
          data_base64: encoded, byte_length: bytes.byteLength };
      }
      scope(context);
      return { ok: true, document: info(), data };
    } catch (error) { return errorResult(error); }
  }
  function close() { active = false; initialized = false; }
  return { initialize, dispatch, close };
}

if (typeof module !== "undefined" && module.exports) module.exports = { createFigmaRuntime };
