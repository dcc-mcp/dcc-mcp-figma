"""Explicit local adapter commands; no installer or credential creation."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import threading


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "runtime-preflight", help="Check the existing shared Runtime without installing or starting it."
    )
    prepare = commands.add_parser("prepare-plugin", help="Prepare files using an existing Figma-assigned ID.")
    prepare.add_argument("--plugin-id", required=True)
    prepare.add_argument("--bridge-port", type=int, default=19061)
    prepare.add_argument(
        "--output-dir", required=True, help="New directory; existing files are never replaced."
    )
    serve = commands.add_parser("serve", help="Start the explicitly approved loopback adapter.")
    serve.add_argument("--bridge-port", type=int, default=19061)
    serve.add_argument("--mcp-port", type=int, default=0)
    serve.add_argument("--registry-dir")
    serve.add_argument("--token-env", default="DCC_MCP_FIGMA_TOKEN")
    serve.add_argument(
        "--request-timeout", type=float, default=30.0, help="Plugin deadline in seconds, at most 120."
    )
    args = parser.parse_args()
    if args.command == "runtime-preflight":
        from .runtime_preflight import runtime_preflight

        report = runtime_preflight()
        print(json.dumps(report))
        return 0 if report["ready_for_launch"] else 2
    if args.command == "prepare-plugin":
        from .manifest import prepare_plugin

        try:
            print(json.dumps(prepare_plugin(args.plugin_id, args.bridge_port, args.output_dir)))
        except (ValueError, FileExistsError):
            parser.error("Plugin preparation requires an assigned ID, valid port and new output directory.")
        return

    from .binding import FigmaBinding
    from .http_bridge import PluginHttpBridge
    from .server import FigmaMcpServer

    token = os.environ.get(args.token_env)
    if not token:
        parser.error(
            "The operator must approve pairing and supply a token through the selected environment variable."
        )
    if not 1024 <= args.bridge_port <= 65535 or not 0 <= args.mcp_port <= 65535:
        parser.error("Use a plugin port between 1024 and 65535 and a valid MCP port.")
    if not math.isfinite(args.request_timeout) or not 0 < args.request_timeout <= 120:
        parser.error("The request timeout must be finite and between zero and 120 seconds.")
    try:
        binding = FigmaBinding(token, timeout=args.request_timeout)
    except ValueError:
        parser.error(
            "The operator-provided pairing token must contain 32 to 256 printable ASCII characters without spaces."
        )
    transport = PluginHttpBridge(binding, port=args.bridge_port)
    server = FigmaMcpServer(binding, port=args.mcp_port, registry_dir=args.registry_dir)
    stop = threading.Event()
    previous = {}
    try:
        transport.start()
        handle = server.start()
        for number in (signal.SIGINT, signal.SIGTERM):
            previous[number] = signal.signal(number, lambda *_args: stop.set())
        print(
            json.dumps(
                {
                    "mcp_url": handle.mcp_url(),
                    "plugin_bridge": transport.url,
                    "plugin_status": binding.status()["state"],
                    "native_acceptance": "unverified",
                }
            ),
            flush=True,
        )
        while not stop.wait(0.5):
            pass
    finally:
        transport.close()
        server.close()
        for number, handler in previous.items():
            signal.signal(number, handler)


if __name__ == "__main__":
    raise SystemExit(main())
