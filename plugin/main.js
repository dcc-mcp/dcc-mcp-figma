/* Concatenate blueprint.js and runtime.js before this file when preparing the plugin. */
"use strict";

(function () {
  let currentSession = null;
  figma.showUI(__html__, { width: 380, height: 300, themeColors: true });

  function isCurrent(session) {
    return currentSession === session && !session.stopped;
  }
  function stop(session = currentSession) {
    if (!session) return;
    session.stopped = true;
    if (currentSession === session) currentSession = null;
    if (session.runtime) session.runtime.close();
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
  function enqueue(session, message, work) {
    session.queue = session.queue.then(async () => {
      if (isCurrent(session)) await work();
    }).catch(() => {
      if (!isCurrent(session)) return;
      stop(session);
      if (message.type === "initialize") {
        figma.ui.postMessage({ type: "initialized", instance_id: message.instance_id,
          result: { ok: false, error: "host_error" } });
      } else {
        figma.ui.postMessage({ type: "response", instance_id: message.instance_id, request_id: message.request_id,
          result: { ok: false, error: "host_error" } });
      }
    });
  }
  function receive(message) {
    if (!message || typeof message !== "object" || Array.isArray(message)) return;
    if (message.type === "initialize") {
      if (!exactFields(message, ["type", "instance_id"])) return;
      stop();
      if (typeof message.instance_id !== "string" || !message.instance_id || message.instance_id.length > 128) {
        figma.ui.postMessage({ type: "initialized", instance_id: message.instance_id,
          result: { ok: false, error: "invalid_arguments" } });
        return;
      }
      const session = { instanceId: message.instance_id, runtime: null, stopped: false, queue: Promise.resolve() };
      currentSession = session;
      enqueue(session, message, async () => {
        session.runtime = createFigmaRuntime(figma, { instanceId: session.instanceId });
        const result = await session.runtime.initialize();
        if (!isCurrent(session)) return;
        figma.ui.postMessage({ type: "initialized", instance_id: session.instanceId, result });
      });
      return;
    }
    if (message.type !== "request" || !exactFields(message, ["type", "instance_id", "request_id", "method", "params"]) ||
        !validId(message.request_id)) return;
    const session = currentSession;
    if (!session || session.stopped || message.instance_id !== session.instanceId) {
      figma.ui.postMessage({ type: "response", instance_id: message.instance_id, request_id: message.request_id,
        result: { ok: false, error: "stale_instance" } });
      return;
    }
    enqueue(session, message, async () => {
      const result = await session.runtime.dispatch(message.method, message.params);
      if (!isCurrent(session)) return;
      figma.ui.postMessage({ type: "response", instance_id: session.instanceId,
        request_id: message.request_id, result });
    });
  }
  figma.ui.onmessage = message => {
    if (message && message.type === "stop") {
      if (exactFields(message, ["type", "instance_id"]) && currentSession && message.instance_id === currentSession.instanceId) stop();
      return;
    }
    receive(message);
  };
  figma.on("close", () => stop());
}());
