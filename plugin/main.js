/* Concatenate runtime.js before this file when preparing the plugin. */
"use strict";

(function () {
  let runtime = null;
  let instanceId = null;
  let queue = Promise.resolve();
  figma.showUI(__html__, { width: 380, height: 300, themeColors: true });

  function stop() {
    if (runtime) runtime.close();
    runtime = null;
    instanceId = null;
  }
  function validId(value) {
    return (typeof value === "string" && value.length > 0 && value.length <= 200) ||
      (Number.isSafeInteger(value) && value >= 0);
  }
  function exactFields(message, expected) {
    return message !== null && typeof message === "object" && !Array.isArray(message) &&
      Object.keys(message).length === expected.length &&
      expected.every(key => Object.prototype.hasOwnProperty.call(message, key));
  }
  async function receive(message) {
    if (!message || typeof message !== "object" || Array.isArray(message)) return;
    if (message.type === "initialize") {
      if (!exactFields(message, ["type", "instance_id"])) return;
      stop();
      if (typeof message.instance_id !== "string" || !message.instance_id || message.instance_id.length > 128) {
        figma.ui.postMessage({ type: "initialized", instance_id: message.instance_id,
          result: { ok: false, error: "invalid_arguments" } });
        return;
      }
      instanceId = message.instance_id;
      runtime = createFigmaRuntime(figma, { instanceId });
      const current = runtime;
      const result = await current.initialize();
      figma.ui.postMessage({ type: "initialized", instance_id: message.instance_id, result });
      return;
    }
    if (message.type !== "request" || !exactFields(message, ["type", "instance_id", "request_id", "method", "params"]) ||
        !validId(message.request_id)) return;
    let result = { ok: false, error: "stale_instance" };
    if (runtime && message.instance_id === instanceId) {
      result = await runtime.dispatch(message.method, message.params);
    }
    figma.ui.postMessage({ type: "response", instance_id: message.instance_id,
      request_id: message.request_id, result });
  }
  figma.ui.onmessage = message => {
    if (message && message.type === "stop") {
      if (exactFields(message, ["type", "instance_id"]) && message.instance_id === instanceId) stop();
      return;
    }
    queue = queue.then(() => receive(message)).catch(() => {
      stop();
      if (message && message.type === "initialize") {
        figma.ui.postMessage({ type: "initialized", instance_id: message.instance_id,
          result: { ok: false, error: "host_error" } });
      } else if (message && message.type === "request" && validId(message.request_id)) {
        figma.ui.postMessage({ type: "response", instance_id: message.instance_id, request_id: message.request_id,
          result: { ok: false, error: "host_error" } });
      }
    });
  };
  figma.on("close", stop);
}());
