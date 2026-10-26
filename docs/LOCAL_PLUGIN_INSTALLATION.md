# Local development plugin installation

Reviewed 2026-10-25. This is a preparation guide, not an installation receipt,
recorded demonstration, native acceptance result or first release.

**Native installation, pairing, design application, editing, save/close/reopen
and post-reopen export are all NOT_RUN. The demonstration is NOT_RECORDED.**
The selected route is local development-plugin deployment. Community
publication and managed Runtime readiness remain separate gates.

## Understand the three packages

| Material | Purpose | What it does not provide |
| --- | --- | --- |
| `DCC-MCP-Login-Offline-Public-Candidate.zip` | An unselected offline design candidate: six desktop/mobile state SVG/PNG pairs, artwork data, tokens, licenses and evidence | An installed plugin, native Figma components, actual node IDs or a `.fig` file |
| Local plugin kit | Generated `manifest.json`, `code.js` and `ui.html`, using a real Figma-assigned development-plugin ID | A Python interpreter, shared Runtime installation, pairing credential or file permission |
| Shared DCC-MCP Runtime and adapter | The external Python service, its Core dependency and a supported deployment lifecycle | Python inside Figma or permission to operate its desktop/document |

The design ZIP contains
`docs/showcase/dcc-login-workspace/manifest.json`. This is an **artwork
inventory**, identified by `artifact_kind: offline_unselected_candidate`.
It is not a Figma plugin manifest and must not be selected in Figma's plugin
import dialog. The ZIP contains no importable plugin manifest, actual plugin
ID, private adapter implementation, `.fig` file or native Figma document.
Its PNGs are offline renders; importing its SVGs does not create the intended
native components, variants, Auto Layout or variable bindings.

The plugin UI pairs an external service. It does not contain an "import design
ZIP" action. The design connection is:

```text
approved design source → offline compiler → validated strict wire.json
                                          ↓
external adapter / Core MCP ↔ approved local plugin → Figma Plugin API
```

Do not send the candidate ZIP, artwork-inventory manifest or offline source IR
directly to `figma_design__apply_blueprint`. That tool accepts the strict wire
schema. No candidate-ZIP importer is supplied by this guide.

## Managed Runtime remains BLOCKED

The reviewed shared Runtime provides selection, manifest negotiation and
installation-plan data. Its inspected release does not establish a complete,
verified Python payload, supported adapter launcher, dependency isolation,
actual runtime probe or Figma manifest deployment. A successful handshake is
not integrity, launch readiness or pairing authority.

Use the existing read-only `runtime-preflight` diagnostic. It currently keeps
`ready_for_launch: false`; do not treat it as a launcher. There is no supported
managed Runtime installation/start command to provide here. Do not invent a
Python downloader, environment manager, implicit package installation or
interpreter fallback. See [Shared Runtime integration](RUNTIME_INTEGRATION.md).

The existing `serve` entry is an **explicit development/test path**, not managed
Runtime deployment. It must not be presented as the missing Runtime launcher
or an installation-ready first release.

A **development preparation kit** has been delivered separately for review,
containing an unpublished adapter wheel, strict wire, compiler/trial scripts,
plugin preparation assets and verification notes. It is not a release asset,
installed plugin, native `.fig` file or verified Runtime. The package's pinned
source and wheel digest must be checked before use; see
[the canonical wheel and proposed Runtime contract](RUNTIME_INTEGRATION.md#proposed-staged-launch-contract).
Preparing or receiving it grants no installation, pairing or execution authority.
Keep pairing secrets, private execution receipts and unapproved source material
outside any public kit.

## Prerequisites

- An existing authorized Figma Desktop target, exactly bound through the
  approved Host and its coordinated desktop slot. An unchanged access denial
  stops the workflow; do not change ACLs, identities or providers to bypass it.
- An owned editable Figma Design file and an approved empty disposable page.
  Plugin eligibility and exact available fonts must be observed, not assumed.
- A genuine Figma-assigned development-plugin ID. Reuse an approved existing
  ID where available. The template placeholder and arbitrary numeric IDs do
  not establish an assigned identity.
- An existing approved pairing supplied by the operator's secret provider.
  Reuse it only within its approved scope. No token value belongs in commands,
  source files, screenshots, logs or recordings.
- Specific approval before creating a **new persistent pairing token**, if one
  is needed, or enabling a new network permission. Approval must identify the
  exact purpose, local endpoint and scope. This guide creates neither.

A plugin ID, operation UUID, connection ID or document marker is not a pairing
credential or grant. Local execution also does not independently establish
distribution or service-policy compliance; see
[Publication boundaries](PUBLICATION_AND_ROUTES.md).

## Prepare the plugin kit

Figma's official development procedure uses Figma Desktop. With a Design file
open, **Plugins → Development → New plugin** can create a development identity;
the documented quickstart selects Figma Design and Custom UI. Alternatively,
reuse an existing assigned development ID. See
[Create a classic plugin for development](https://help.figma.com/hc/en-us/articles/360042786733-Create-a-classic-plugin-for-development)
and [Plugin Quickstart](https://developers.figma.com/docs/plugins/plugin-quickstart-guide/).

`plugin/manifest.template.json` is **not directly importable**. After the
operator supplies the real assigned ID, use the already provisioned environment
to run the existing preparation command. Replace the placeholders before use:

```text
python -m dcc_mcp_figma prepare-plugin --plugin-id <FIGMA_ASSIGNED_ID> --bridge-port 19061 --output-dir <NEW_PRIVATE_KIT_DIRECTORY>
```

Preparation refuses an existing output directory. It produces:

```text
<NEW_PRIVATE_KIT_DIRECTORY>/
  manifest.json
  code.js
  ui.html
```

`code.js` combines the blueprint engine, runtime and main entry. Preparation
does not import, install, run or authorize the plugin. Retain the generated
files' hashes and assigned-ID provenance before native testing.

The prepared manifest uses `editorType: ["figma"]`,
`documentAccess: "dynamic-page"`, `main: "code.js"` and `ui: "ui.html"`.
Its normal network allow-list remains `["none"]`; its development scope is
exactly `http://127.0.0.1:19061`. No wildcard, current-user, private,
team-library or proposed-API permission is added. Figma documents these fields
in [Plugin Manifest](https://developers.figma.com/docs/plugins/manifest/).
Declaring that development endpoint is not evidence that its permission has
been approved in the target host.

## Import, start and pair

In the approved Figma Desktop window, open the owned Design file and choose
**Figma menu → Plugins → Development → Import new plugin from manifest…**.
Select the **generated kit's** `manifest.json`, not the design candidate's
artwork inventory. Confirm the intended local development entry, then run it
from Development. This is the official
[local import procedure](https://help.figma.com/hc/en-us/articles/360042786733-Create-a-classic-plugin-for-development),
not a recorded action performed by this project.

Managed service startup stays blocked until its Runtime contracts are ready.
If an explicit development run is separately selected, label it as such and
retain its actual process/version evidence. The plugin bridge uses loopback
port **19061**. Core MCP uses a **different, automatically assigned port** when
the default `--mcp-port 0` is retained. Use the printed `mcp_url`; do not assume
19061 is the MCP endpoint. Any changed bridge port must match the manifest and
plugin UI and needs its exact scope reviewed.

Pair only with the already approved local service, using the existing secret
provider. Keep the plugin open. Connecting and reading do not create design
nodes; the first explicit write creates a plugin-scoped correlation marker,
never the token.
The existing approved token must be 32–256 printable ASCII characters without
spaces; no new token is generated by this guide. A stopped UI makes one bounded
disconnect attempt. Lost unload notifications are handled by a 30-second idle
lease; active requests retain their existing deadline protection. Reconnection
is explicit and never automatically reapplies an uncertain operation.

The UI timer update uses the bound request deadline, capped at 120 seconds,
while initialization retains a 30-second limit. This revision still requires
exact-head validation and native timing acceptance. Timeout hints do not grant
more time or permission. On timeout, stop, retain known receipts and do not
replay an uncertain apply.

## Native demonstration checklist

Every execution step is currently **NOT_RUN**. Blocked prerequisites stop
dependent steps. Source preparation, synthetic tests and CI success do not
advance these native states.

| Step | Required real observation | State |
| --- | --- | --- |
| Install external service | Verified shared Runtime/interpreter/Core/dependencies, isolation and exact adapter wheel | NOT_RUN; managed route BLOCKED |
| Prepare and import kit | Real assigned ID, generated file hashes and actual Development entry | NOT_RUN |
| Start service and pair | Real endpoints/process, approved pairing and selected document/page | NOT_RUN |
| Apply blueprint once | Empty page; strict wire digest; actual run-root/node/component/variable IDs | NOT_RUN |
| Read and edit | Editable text, component/instance/variant associations, Auto Layout, actual aliases and same-ID before/after properties | NOT_RUN |
| Save, close and reopen | Trusted save state and exact-file identity, actual close/reopen, fresh connection and same-ID readback | NOT_RUN |
| Export after reopening | Six actual PNG/SVG pairs, timestamps, MIME, dimensions/length/SHA and consumer inspection | NOT_RUN |

The existing compiler writes strict `wire.json` and a conversion report to a
new directory. Compilation does not access Figma or turn offline logical IDs
into real IDs. Keep approved source and wire private when their publication
rights have not been established.

After the prerequisites are met, `scripts/native_blueprint_trial.py` discovers
the live descriptors, applies once, checks actual typed structure and exports
six screens. Its `reconnect-readback` phase uses the previous operation and
wire digest, a new connection, matching document/marker and the same actual IDs.
Read the [blueprint trial procedure](BLUEPRINT.md) for its existing command
interface. Operation IDs are correlation only. Core job `completed` is not
success without the inner result and semantic checks.

For an independent bounded edit, `scripts/native_trial.py` creates, updates and
reads one frame. Use a separately approved empty disposable page and separate
receipts; do not pollute the showcase page and then claim it was empty. Do not
automatically delete, restore or replay work after an uncertain result.

### Save/reopen and export evidence are separate

Have the trusted Host establish the actual save state and exact file identity,
close that file and reopen the same file. Restart the same assigned plugin ID
and reconnect before typed readback. A copied file can retain markers, so
matching name/page/marker is not independent file-identity proof.

Reconnection, undo, `commitUndo` and version-history actions cannot substitute
for real save/close/reopen evidence. The trial deliberately keeps persistence
unverified; its readback does not perform or prove those GUI lifecycle events.

The blueprint **write phase exports before reopening**. Its
`reconnect-readback` phase only reads. The optional `reconnect-export` phase
uses the same completed write receipt, verifies the fresh connection, same
wire/document/IDs and full typed structure, then calls the discovered
`figma_nodes__export` for each of the six screens as PNG and SVG. Use a new
output directory and retain its fresh receipt. Neither reconnect phase
reapplies, saves, closes or reopens the file. Independent trusted Host evidence
is still required to identify those exports as post-reopen evidence. Inspect
the real files; do not relabel earlier exports as newly generated ones.

## Recording plan — NOT_RECORDED

| Shot | Planned content | Evidence boundary |
| --- | --- | --- |
| 1 | Show the six offline screens and three deliverable roles | Label the renders OFFLINE, not a Figma capture |
| 2 | Show generated kit identity and Development import | Real assigned ID and file hashes; no token or private path |
| 3 | Show actual service/Runtime state and distinct bridge/MCP ports | If blocked, show BLOCKED and stop the native segment |
| 4 | Pair, show selected empty page and live descriptors | Exclude secret entry, clipboard, headers, account and file URL |
| 5 | Apply once and inspect native layers/text/components/layout/variables | Actual IDs and alias evidence retained privately |
| 6 | Demonstrate bounded same-ID edit/read | Separate receipts; no replay or rollback on uncertainty |
| 7 | Show real save state, same-file close/reopen and typed readback | Continuous trusted lifecycle evidence, not a reconnect montage |
| 8 | Export six PNG/SVG pairs after reopening and inspect them | Record actual timing, dimensions/length/hash and visual limits |
| 9 | Summarize passed evidence and unresolved gates | Do not imply managed installation, native acceptance or release readiness without proof |

No installation video is delivered by this document. Do not stage a live
success, splice offline images into a supposed native demonstration, publish
private source/receipts or treat the development preparation kit as a first release.
See [First release acceptance](FIRST_RELEASE_GATES.md).
