# Development status

Checked 2026-10-26. This document makes the development work discoverable from
the default branch; it does not distribute or release the adapter.

## Source and setup

The actual default branch is `main`. The adapter implementation is in
[draft PR #1](https://github.com/dcc-mcp/dcc-mcp-figma/pull/1), not in the default
branch. The reviewed implementation snapshot is
[`b7d1dc108bd0f334754aa00af8ebbd6b6e65af81`](https://github.com/dcc-mcp/dcc-mcp-figma/tree/b7d1dc108bd0f334754aa00af8ebbd6b6e65af81).
Check the PR's current head before reproducing results; the evidence below is
bound to that snapshot, not to future commits.

Read the pinned
[local plugin installation guide](https://github.com/dcc-mcp/dcc-mcp-figma/blob/b7d1dc108bd0f334754aa00af8ebbd6b6e65af81/docs/LOCAL_PLUGIN_INSTALLATION.md)
and [release gates](https://github.com/dcc-mcp/dcc-mcp-figma/blob/b7d1dc108bd0f334754aa00af8ebbd6b6e65af81/docs/FIRST_RELEASE_GATES.md).
An offline artwork ZIP is not an installable plugin or native `.fig` document.
The generated plugin kit needs a real Figma-assigned development-plugin ID;
the checked-in template cannot be imported unchanged. Preparing the kit does
not import, install, start or pair it. No released package or installation-ready
managed Runtime bundle is supplied by this default branch.

The selected route is a local development plugin using the official JavaScript
Plugin API, with an external Python adapter. Figma has no embedded Python for
this adapter. The preferred external service uses the shared DCC-MCP Runtime;
this project does not provide another interpreter downloader or installer.
Community publication remains on hold. See the pinned
[publication boundaries](https://github.com/dcc-mcp/dcc-mcp-figma/blob/b7d1dc108bd0f334754aa00af8ebbd6b6e65af81/docs/PUBLICATION_AND_ROUTES.md).
The pinned implementation includes its [MIT license](https://github.com/dcc-mcp/dcc-mcp-figma/blob/b7d1dc108bd0f334754aa00af8ebbd6b6e65af81/LICENSE);
retain applicable third-party asset notices separately when reusing artwork.

## Validation boundaries

| Evidence at the pinned snapshot | Result | What it establishes |
| --- | --- | --- |
| [Adapter contracts CI](https://github.com/dcc-mcp/dcc-mcp-figma/actions/runs/40220544291) | Three jobs passed: Linux Python 3.10/3.12 and Windows Python 3.12 | Each ran 414 Python and 248 Node tests, lint/format checks and an unpublished wheel build; Plugin API harness results are synthetic |
| Canonical unpublished wheel audit | 17/17 Python/plugin source members match raw Git blobs; 21/21 hashed RECORD entries pass | Artifact/source correspondence, not installation, signature trust or native acceptance |
| Native plugin installation and pairing | NOT_RUN | No accepted assigned plugin identity and live document connection for this run |
| Native editable design, save/close/reopen and post-reopen PNG/SVG export | NOT_RUN | Offline renders, synthetic tests and reconnect readback do not establish these steps |
| Installation recording, first release and showcase acceptance | Pending | Public source or this documentation merge does not complete those gates |

The canonical development wheel is `dcc_mcp_figma-0.1.0-py3-none-any.whl`,
63,920 bytes, SHA-256
`611e5afca59f861b71ef6ff41d19ce315be05fa813311fdc40f3d3efc97c5a39`.
Its source pin is the implementation snapshot above. The historical 61,707-byte
wheel with SHA-256
`9a1337f6cbd3ff030ee115092b00e20b8734a38eea90fcc7c29bcbc1d388880a`
is stale and must not be substituted. These identifiers are for development
artifact comparison; this page supplies neither wheel nor permission to install
one. A wheel digest alone is not a complete independently trusted Runtime lock.

## Shared Runtime: released and proposed contracts

The inspected released baseline is
[Runtime v0.2.0](https://github.com/dcc-mcp/dcc-mcp-runtime/releases/tag/v0.2.0),
source [`3a54f666c4283bab160dbab3ac90630c9ed39087`](https://github.com/dcc-mcp/dcc-mcp-runtime/tree/3a54f666c4283bab160dbab3ac90630c9ed39087).
It does not deliver an accepted complete CPython payload, deployed Figma
manifest or managed adapter launch. Figma's existing `runtime-preflight` uses
the released selection/negotiation APIs and keeps `ready_for_launch: false`.

[Runtime draft PR #5](https://github.com/dcc-mcp/dcc-mcp-runtime/pull/5), inspected
at [`da6cb6024a15941722bb3af7fdd7e61819fadc36`](https://github.com/dcc-mcp/dcc-mcp-runtime/tree/da6cb6024a15941722bb3af7fdd7e61819fadc36),
adds complete-inventory verification, an explicitly authorized bounded metadata
probe of an already staged interpreter, and Core launch-plan data. It does not
download, install, activate or start the adapter. The Figma preflight has not
adopted that draft API, and this document does not invoke it. See its pinned
[staged-launch contract](https://github.com/dcc-mcp/dcc-mcp-runtime/blob/da6cb6024a15941722bb3af7fdd7e61819fadc36/docs/STAGED-LAUNCH.md).

Figma's production dependency remains `dcc-mcp-core>=0.20.44,<0.21`.
The wheel is pure Python and declares Python >=3.7; that declaration does not
establish a Python 3.7 source install or native aggregate acceptance. The optional
trial client uses `mcp>=1.27,<2` on Python >=3.10. Pytest and Hatchling are not
production dependencies. The candidate `cp311-win_amd64` Runtime target is a
declaration, not an observed interpreter/ABI result.

Remaining managed-deployment work belongs to the shared Runtime lifecycle:
an independently approved complete payload/dependency inventory, actual staged
interpreter/ABI/Core checks, immutable staging and host-owned launch. Native
acceptance additionally needs an approved existing Figma target, assigned plugin
identity, approved pairing and actual same-file save/reopen/export evidence.
Desktop access denial or missing scope must stop the affected operation; it
does not justify another identity, provider, permission or interpreter route.

Documentation may be reviewed and merged on its own scope. The adapter merge,
first release and showcase submission retain their native and publication gates.
