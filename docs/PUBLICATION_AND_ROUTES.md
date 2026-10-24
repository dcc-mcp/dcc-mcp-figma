# Publication hold and complementary integration assessment

Reviewed 2026-10-24. This is a source-backed product assessment, not a grant of
permission or a legal conclusion. The user subsequently selected local
development-plugin deployment and authorized local configuration and a
corresponding organization repository, with private visibility protected.
The existing implementation, tests and native-validation gaps remain unchanged.
There has been no submission, publication, deletion, official contact or attempt
to conceal functionality.

## Distribution boundary

Figma's [Community review guidelines](https://help.figma.com/hc/en-us/articles/360039958914-Plugin-and-widget-review-guidelines)
encourage complementary AI features but generally reject plugins that expose
MCP or enable programmatic AI access outside the official MCP server. They also
identify duplication of Figma agent/MCP capabilities and paid-offering
workarounds as rejection grounds. Our editor-plugin-to-MCP architecture fits
that stated concern; Community publication is not an assumed viable route.
This is an assessment of review risk, not a statement that every MCP use is
prohibited.

Local execution and test results are not distribution approval. An
[internal organization distribution mechanism](https://help.figma.com/hc/en-us/articles/4404228629655-Create-internal-plugins-for-an-organization)
does not independently clear this design. Figma's
[Developer Terms](https://www.figma.com/legal/developer-terms/) cover use of its
APIs, SDKs and MCP resources, including permitted integration scope and
credentials. Private-use compliance remains unresolved; the repository's MIT
license covers our code, not Figma's service rights.

## Official capability and access boundary

The [official remote server](https://developers.figma.com/docs/figma-mcp-server/)
supports design context and native canvas writing. Its
[`use_figma` route](https://developers.figma.com/docs/figma-mcp-server/write-to-canvas/)
can build editable frames, components, variants, variables and auto layout.
Actual tool schemas and results must be observed in the authorized client.
Existing Plugin API arguments or export envelopes must not be assumed to match.
The documented write output limit is 20 KB per call; the current local bridge's
1 MiB export envelope cannot simply be forwarded unchanged.

Connection is restricted to [supported clients](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/).
A new client requires Figma's onboarding route. An existing client's connector
bundle is different from this repository's Figma editor plugin. We cannot
assume that a new DCC service, transparent proxy or reused credential is an
authorized official MCP client. No onboarding request or new authorization has
been initiated.

## Candidate direction: official Figma access, DCC-specific value

This is a recommendation for user consideration, not an implemented migration.

| Layer | Proposed complementary responsibility | Existing material to reuse |
| --- | --- | --- |
| Figma access | The user's supported, authorized client invokes official MCP tools and preserves Figma's access checks | Target/readback discipline and failure-state vocabulary; no credential or transport reuse assumption |
| DCC workflow | Coordinate UI/asset requirements, sizing, naming, versioned handoff and authorized DCC imports | Typed validation concepts, schemas and test cases after mapping to actual official descriptors |
| Templates and skills | DCC-specific component/layout briefs and repeatable workflow instructions using the official server | Trial scenarios and design-system checks; no hidden alternative MCP or paid-feature bypass |
| Acceptance | Verify real IDs/properties, official response completeness, export provenance and saved/reopened state | Hash/length checks, asynchronous terminal-result validation and indeterminate-outcome handling |

The plugin pairing UI, custom HTTP transport, local bearer-token flow and editor
runtime remain preserved research code. They are not required by the proposed
official-client route and must not be relabeled as official access. Existing
synthetic tests remain useful regression vectors, not native-host or policy
acceptance evidence. A genuine saved/reopened-file check and reliable export
still require a concrete supported-client workflow and observed evidence.

## Selected route and remaining boundaries

Proceed with the retained local development-plugin implementation within the
user's authorization. No Community publication, hidden functionality, payment,
account creation or terms/access-control workaround is authorized. Local
deployment is not a blanket compliance conclusion. New persistent credentials
require a concrete parameter-specific confirmation; do not reveal secrets.
If the current desktop context still denies access, stop UI attempts and report
the exact Host/PID/HWND binding gap without changing providers or desktops.

The official-client complementary route remains an evaluated alternative, not
an implemented migration. Its remote connection needs a supported authorized
client and file access; write-to-canvas is currently a free beta on eligible
plans, with future usage pricing unspecified. Dev seats are limited to writing
their own Drafts; writing elsewhere requires Full. Read-call quotas and
AI-credit-consuming tools are separate costs. See the
[seat FAQ](https://help.figma.com/hc/en-us/articles/39252411778583-Figma-MCP-server-FAQs)
and [current limits](https://developers.figma.com/docs/figma-mcp-server/rate-limits-access/).
