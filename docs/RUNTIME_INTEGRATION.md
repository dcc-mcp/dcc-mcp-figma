# Shared Runtime integration

Figma has no embedded Python interpreter. The selected deployment architecture
uses DCC-MCP Runtime for the external Python adapter service and the official
JavaScript Plugin API inside Figma. Runtime is not Python inside the editor,
the Rust `dcc-mcp-server sidecar` command, the gateway daemon, or Monica's model
runtime. It does not grant Figma file, plugin, desktop, loopback or credential
permissions.

## Verified public contract

The reviewed canonical Runtime source is
[`3a54f666c4283bab160dbab3ac90630c9ed39087`](https://github.com/dcc-mcp/dcc-mcp-runtime/tree/3a54f666c4283bab160dbab3ac90630c9ed39087).
No Runtime installation or active-environment modification was performed.

| Concern | Existing contract | Current boundary |
| --- | --- | --- |
| Selection | `dcc_mcp_runtime.bootstrap.runtime_root()` accepts `DCC_MCP_RUNTIME_ROOT`, otherwise derives a package-relative root | Figma preflight delegates selection to that helper; no shell/PATH Python selection or guessed payload executable |
| Manifest negotiation | `require_adapter("figma")` loads `runtime/manifest.json` and `runtime/manifests/figma.json`; rejection raises a stable handshake failure | The release includes Adobe, CapCut and OBS entries, with no Figma manifest |
| Version / ABI | Runtime package is 0.2.0 and supports Python >=3.9; its separate manifest says runtime 0.1.0, Python 3.11 and `cp311-win_amd64` | Package syntax support and a payload's target ABI are different facts; negotiation does not probe the running interpreter |
| Core compatibility | Current handshake compares Core requirement strings for exact equality | Runtime says `>=0.19.13,<1.0.0`; Figma requires `>=0.20.44,<0.21`. Do not widen Figma's actual requirement just to pass equality |
| Integrity | Runtime manifest hash/signature are null; example adapter wheel hashes are placeholders | A capability fingerprint or an accepted handshake is not a verified payload, wheel signature or permission |
| Installation / launch | Published CLI exposes `validate-manifest`; bootstrap explicitly delegates process creation to adapter/Core | Reviewed 0.2.0 assets contain a small wheel/sdist, manifests and migration notes; no published CPython payload, executable launcher or installer |
| Dependencies / isolation | No public shared-environment isolation/installation contract was found in the reviewed source | Do not create an adapter-owned Python download, venv manager, implicit pip install or fallback |
| Core lifecycle | Core `doctor --adapter-python figma=ABSOLUTE_PYTHON` can diagnose an explicitly supplied interpreter; `start-instance` consumes an existing launch plan | These do not select/install the shared Runtime or supply its missing launch plan |

The existing Core CLI's `--no-update-maintenance` flag can skip update
maintenance in source. Its presence in the installed executable was not tested;
no retry of a previously denied staged update was performed for this work.

## Adapter change

`python -m dcc_mcp_figma runtime-preflight` is a read-only check. It validates
shared selection and delegates to the public bootstrap when available.
It returns bounded reasons without raw exception, local-root, environment or
handshake payload disclosure. Missing packages/manifests, access denial and
incompatible negotiation stop the check. There is no automatic retry, install,
interpreter fallback, process creation or token generation.

Even an accepted synthetic or actual handshake leaves `success: false` and
`ready_for_launch: false` until shared trusted-payload, launch, dependency
isolation and actual runtime-probe contracts exist. This is deliberate: this
change provides honest integration diagnostics, not a new Runtime launcher.
The existing explicit `serve`, preparation and developer/test APIs remain
compatible; they are not evidence of a managed Runtime deployment.

Tests inject an explicitly synthetic bootstrap API. They exercise shared selection,
supported package Python versions, missing/denied manifests, ABI/Core rejection,
bounded errors and the difference between negotiation and launch readiness.
PC8 currently has no installed `dcc_mcp_runtime` package in the checked Python
3.12 environment and no selected `DCC_MCP_RUNTIME_ROOT`; actual managed launch
and native Figma read/write/save/reopen/export remain unverified.

## Shared-owner handoff

The Runtime owner must publish the supported payload layout and process entry,
trusted versioned manifests and integrity verification, interpreter/Core/native
dependency probes, isolated adapter dependency lifecycle, and the supported
Figma manifest install/upgrade contract. Core constraints need a real compatible
intersection or another explicit shared version policy, not string rewriting.
No Figma manifest with a fake wheel digest or implied signature is installed.

Creator's owner can reuse the following decision rule in its canonical rules,
templates and tests:

1. A host with embedded Python first validates its actual version, ABI and
   dependencies against the adapter contract.
2. A host without Python that needs a Python service prefers existing DCC-MCP
   Runtime and its shared selection, verified installation and isolation
   contracts. Missing, offline, incompatible or denied Runtime stops at a
   specific preflight result, without a custom interpreter download.
3. A suitable official JS/native bridge remains valid without forcing Python
   into the host. If an external Python service is used, its lifecycle and host
   API boundary remain explicit.

The coordinator owns Creator follow-up and overlap with Core installation
contracts. This repository changes Figma only; it does not patch another
owner's checkout or install/release Runtime.
