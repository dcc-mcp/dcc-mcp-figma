# Typed editable design blueprints

`figma_design__apply_blueprint` creates a new owned run container in the paired
page. `figma_design__read_blueprint` reads that observed container and its
recorded local resources. These are data operations, with no eval, arbitrary
property path, remote asset URL, library permission or Python inside Figma.

The v1 wire is separate from the offline design's provenance record. The compiler
does not copy its permission flags or interpret them as authorization. It rejects
unsupported fields rather than silently converting the design to a screenshot.
The public MCP schema describes the typed fields; Python and JavaScript both
validate the whole graph before document mutation.

## Supported representation

- Frames, local components and variants, instances with typed text/visibility
  overrides, editable text, rectangles, ellipses and bounded vector paths.
- Explicit Auto Layout, child sizing and geometry. A child is appended before
  FILL sizing is assigned. Instances reference components in the same wire.
- One local collection with a single default mode, COLOR/FLOAT variables and
  typed paint/size/radius bindings. No tier upgrade or remote library is assumed.
- Existing editor fonts loaded before the first document write. Missing fonts
  stop the operation; no download or silent replacement occurs.
- PNG image bytes with SHA-256 and dimensions. Original brand pixels remain
  unchanged and use contain fitting. SVG icons compile to native primitives and
  absolute vector paths; an IMAGE wire node becomes a native rectangle with an
  image paint. Native vector names and geometry remain editable.

Text-style declarations are explicitly projected to inline typography in this
first version. The compiler report records this conversion; it does not claim
that native TextStyle resources were created. Non-variant annotations on an
ungrouped component are also explicitly recorded as projection decisions.

Limits are 2 MiB of wire data, 2,048 expanded native nodes, depth 24, 64 variables,
32 component sets, 16 fonts and 1 MiB of decoded images in total. Expanded counts
include the run container, component sets and cloned instance descendants.
JSON, references, cycles, fonts, vector/image data and expanded budgets are
checked before the first document write. Official API behavior and actual native
layout still require host acceptance.

## Prepare and run after native setup

Use an existing development Python and the already approved plugin/pairing setup
from the README. Shared Runtime readiness is a separate, currently unresolved
deployment gate. None of these commands installs an interpreter or credentials.

Compile the retained offline design into a fresh directory:

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
python scripts/compile_login_blueprint.py --source <offline-native-blueprint.json> --output-dir <new-compiled-directory>
```

This writes `wire.json` and `compiler-report.json`; both describe an offline
conversion and keep `native_execution: NOT_RUN`. Reopening or compiling data is
not document persistence. Keep this source and the wire hash for the native run.

Start the explicit development service with a bounded plugin deadline appropriate
for font loading and the full design, using the existing approved token source:

```powershell
python -m dcc_mcp_figma serve --request-timeout 120
```

In the approved empty test page, the native trial discovers the live typed tools,
applies once, reads the actual editable structure and exports the six screen
frames as PNG/SVG into a new directory:

```powershell
python scripts/native_blueprint_trial.py --mcp-url http://127.0.0.1:<printed-port>/mcp --blueprint <compiled-directory>/wire.json --output-dir <new-write-evidence-directory>
```

The client follows Core-owned asynchronous job polling and checks the inner
result. After trusted DCC-CUA evidence establishes that the same file was
actually saved, closed and reopened, reconnect the same plugin and perform only
the readback phase:

```powershell
python scripts/native_blueprint_trial.py --mcp-url http://127.0.0.1:<printed-port>/mcp --blueprint <compiled-directory>/wire.json --phase reconnect-readback --evidence <write-evidence-directory>/receipt.json --output-dir <new-readback-evidence-directory>
```

Readback requires the previous operation, same wire hash, a new connection and
the same observed document marker/node IDs and relevant values. It cannot
establish that the real file was closed/reopened or cloud-saved. No Plugin API
save operation, undo boundary or connection change is presented as that evidence.
Exports retain the existing 1 MiB per-file limit; an oversized actual native
export is a reported failure, not a successful truncated artifact.

To obtain fresh exports on the new connection, use `--phase reconnect-export`
with the same completed write receipt and a different new output directory.
This phase first performs every reconnect-readback check, then calls the real
export tool for all six screens as PNG and SVG. It never reapplies the blueprint
or reuses the earlier export bytes. The receipt labels these exports
`after_reconnect_readback`; native acceptance and persistence remain unverified.
Only independent trusted Host evidence can establish that this connection
actually follows saving, closing and reopening the same file.

Vector paths are authoritative intrinsic geometry: their tight origin and
Bezier-extrema bounds must match the declared bounds within 0.001. Zero-axis
line vectors remain valid; v1 intrinsic vectors cannot use `FILL` sizing, which
would rescale those paths. Other node dimensions must be at least 0.01, matching
Figma's resize limit. Baseline cross-axis alignment requires horizontal Auto
Layout. Readback compares equivalent quadratic/cubic geometry using absolute
tolerance 0.001 and relative tolerance 1e-6 because Figma may normalize
quadratic paths to cubic paths.
Readback checks local x/y for explicitly positioned, non-cloned children in
free layout and applicable absolute positioning. It does not compare generated
root placement, Auto Layout flow or native instance/constraint projections to
unprojected source coordinates; those still need native layout and visual evidence.

## Failure and evidence

An operation ID is correlation data, not a credential, grant or exactly-once
guarantee. An existing tagged run rejects duplicate application. Failure before
tag creation can still leave native objects; never infer that retry is safe.

Every mutation checks the captured instance, document/page, marker and deadline.
A returned partial receipt contains only a fixed stage, completed-step count and
reported actual IDs. Unknown IDs after a lost response stay unknown. Failure or
malformed response invalidates the exact connection, preserves independently
validated reported IDs, and never replays, deletes or rolls back automatically.
Receipts grant no later edit or read authority.

Synthetic tests execute the production bundle and actual Core MCP HTTP/jobs with
an explicitly synthetic Plugin API. They test contracts, not Figma entitlement,
font availability, native geometry, file persistence or visual quality. Retain
these separate scopes in the [first release gates](FIRST_RELEASE_GATES.md) and
[public showcase evidence](SHOWCASE_ACCEPTANCE.md).
