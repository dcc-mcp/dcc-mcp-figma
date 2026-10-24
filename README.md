# DCC-MCP Figma

An independent, unreleased Figma adapter. The local plugin calls the official
Figma Plugin API; `dcc-mcp-core` provides MCP serving, jobs, readiness and
reverse-request correlation. This project is separate from Core's experimental
five-provider session bridge and its runner exit-status fix.

**The selected route is local development-plugin deployment; Community publication is on hold.**
Read the [publication limits and official-MCP complementary assessment](docs/PUBLICATION_AND_ROUTES.md).
The implementation is preserved. Setup still requires a supported, authorized
host and must stop on desktop access denial. Local test success and choosing a
local deployment do not establish private-use compliance.

## Current capability and evidence

| Operation | Implementation | Native Figma acceptance |
| --- | --- | --- |
| Read current page and an observed node | Plugin API, bounded page snapshot | Not run |
| Create and modify a frame | `createFrame`, typed properties and `resize` | Not run |
| Read back the same node IDs | `getNodeByIdAsync`, page and marker checks | Not run |
| Export PNG/SVG | `exportAsync`, byte validation and SHA-256 | Not run |
| Same-file close/reopen persistence | Reconnect readback script plus independent host evidence | Not run |

The tests execute shipping UI/main/runtime code with an explicitly synthetic
browser DOM and Figma API. They also exercise actual Core HTTP, the official
MCP client, plugin HTTP polling and asynchronous export jobs. They do not start
Figma, establish an account, install a plugin, or prove cloud persistence.

## Shared Runtime first

Figma has no embedded Python. The preferred deployment uses the existing
**DCC-MCP Runtime** for this adapter's external Python service. The Figma plugin
still executes official JavaScript Plugin API calls inside Figma. No Python
interpreter is bundled, downloaded or installed by this repository.

Run the read-only preflight from an existing development environment:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python -m dcc_mcp_figma runtime-preflight
```

It delegates root selection to the installed Runtime's public `runtime_root()`
helper, including its `DCC_MCP_RUNTIME_ROOT` override, then manifest negotiation
to `require_adapter("figma")`.
It never chooses an unrelated Python, creates an environment, installs packages,
starts a process or changes pairing/network permissions. JSON output and exit
code 2 explicitly report an unavailable managed launch. A successful manifest
handshake alone still reports `ready_for_launch: false`.

The reviewed Runtime 0.2.0 release contains package/manifest scaffolding but no
published CPython payload or supported adapter-launch command. Its current
manifest also lacks a Figma entry and uses a different Core requirement string
that its equality-only handshake rejects. Managed deployment is blocked on those
shared contracts; see [exact findings and owner handoff](docs/RUNTIME_INTEGRATION.md).
The Python commands below remain explicit developer/test entry points, and do
not establish a managed Runtime installation or launch.

## One-time native setup

First establish an authorized, exactly bound Figma host. With DCC-CUA, preserve
the provider, runtime version, PID and HWND before any UI observation/input;
stop if binding or desktop permission is unavailable. Then obtain an existing
**Figma-assigned development plugin ID**.
Create a local development plugin through Figma Desktop's
**Plugins > Development > New plugin**, or reuse an existing development ID.
Do not publish it. A plugin ID is not a token; never send credentials to chat.
The checked-in manifest is a template with an explicit unusable placeholder.

Once the existing host and permissions are approved:

1. Select an owned, disposable Figma Design file with an empty test page.
2. Prepare local plugin files using its assigned ID. This does not install them:

   ```powershell
   $env:PYTHONPATH = (Resolve-Path ./src).Path
   python -m dcc_mcp_figma prepare-plugin --plugin-id <assigned-id> --output-dir native-evidence/plugin
   ```

3. Have the operator approve the precise development network scope
   `http://127.0.0.1:19061` and supply an approved local pairing token through
   their secret provider as `DCC_MCP_FIGMA_TOKEN`. The token must contain 32 to
   256 non-space characters. This project does not generate or persist it.
   New credentials and permission changes require explicit approval.
4. Start the reviewed loopback adapter, then import/run the prepared manifest
   in Figma and pair through its UI:

   ```powershell
   python -m dcc_mcp_figma serve --bridge-port 19061
   ```

The MCP port is OS-assigned and printed at startup. `--registry-dir` selects an
operator-approved Core registry; no gateway is started or reconfigured. A custom
bridge port must match the prepared manifest and the UI's port field.

The plugin requests no `currentuser`, `activeusers`, team-library, private or
proposed API permission. Its release-domain list is `none`; only the exact
development loopback endpoint is declared. Connection and reads do not write
document data. The first explicit frame write adds a plugin-scoped document
marker containing a correlation ID, never the token. A marker is not a global
file key, ownership proof or protection against copying a file.

## Automated native trial

Use the already installed optional official MCP SDK on Python 3.10 or later.
After the approved plugin is paired in the chosen empty page:

```powershell
python scripts/native_trial.py --mcp-url http://127.0.0.1:<printed-port>/mcp --output-dir native-evidence/write
```

The script discovers the live descriptors, reads the page, creates one frame,
edits it, reads the same ID and exports actual PNG/SVG bytes. It follows the
server-owned `core_poll` route for asynchronous jobs and checks the inner result;
`completed` alone is insufficient. It saves private receipts and hashes and
never retries a mutation or silently selects another file.

After a trusted host has actually closed/reopened the same file and restarted
the same plugin ID, automate the subsequent readback:

```powershell
python scripts/native_trial.py --mcp-url http://127.0.0.1:<printed-port>/mcp --phase reconnect-readback --evidence native-evidence/write/receipt.json --output-dir native-evidence/readback
```

This checks a new connection, matching document/page marker and unchanged node
IDs/properties. Reconnecting alone does not prove a file was closed/reopened or
cloud-saved. The script keeps `persistence: unverified` until independent trusted
host evidence establishes that step. Ordinary plugins cannot use `fileKey` as a
general identifier. `commitUndo` is not save; version-history creation does not
guarantee that all immediately preceding edits are included.

## Runtime boundaries

- Only typed Plugin API methods exist: page read, node read, frame creation,
  frame update and PNG/SVG export. No canvas REST write endpoint or plugin eval
  is invented.
- Each connection owns one Core `ReverseBridgeSession`. Requests pin plugin
  instance, current page, document marker and deadline. Responses must match a
  delivered request in that connection. A timeout closes the entire session so
  queued edits cannot later be polled and executed.
- The transport binds IPv4 loopback, checks Host and browser Origin, compares
  the pairing token in a header, limits bodies and never logs request payloads.
  HTTP success and pairing do not imply native acceptance.
- Core readiness rejects native calls before pairing. Core-owned job status
  remains queryable after a disconnect. Export is an asynchronous Core job.

The public Core composition uses `ToolRegistry`, `McpHttpServer`,
`ReadinessProbe` and `ReverseBridgeSession`. `DccServerBase` currently has no
public direct-handler registration seam; this avoids accessing its private
server or introducing a second script executor.

**Core surface limitation:** Core 0.20.44/0.20.47 also advertise their standard
job/dynamic-tool/group builtins. Their public API has no switch to advertise
only this adapter's six tools. This adapter registers no script executor and
the trial client calls only its discovered native tools and Core job polling.
Core consumes reserved `_meta` transport fields before some Python handlers;
they never enter plugin parameters and grant no pairing or document authority.
Do not describe the complete advertised Core surface as six typed tools. A
public Core filter is a separate Core-owner concern, not an adapter-private
monkeypatch or alternate permission path.

## Local validation

Use an existing development environment; no command installs tools implicitly:

```powershell
python -m pytest tests -q --basetemp=<new-workspace-test-directory>
node --test tests/plugin_runtime.test.cjs
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m build --wheel --no-isolation
```

Native Core 0.20.44 and Node 24 are the local validation baseline. Production
Python sources retain Python 3.7 syntax; official MCP trial scripts require its
Python 3.10+ SDK. No package, catalog install entry or public release is published.
See [official sources](SOURCES.md) and retain verification outputs for the exact
tested commit and remaining host/organization blockers.
