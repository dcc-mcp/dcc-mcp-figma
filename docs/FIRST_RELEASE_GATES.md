# First release acceptance

The current task explicitly authorizes a first merge/release after review, exact
head CI, native Figma acceptance and publication sanitation. That authorization
does not replace the checks below. The repository remains private and local
development-plugin deployment remains the selected route. Community publication
is not authorized.

## Required evidence

| Gate | Required observation | Current boundary |
| --- | --- | --- |
| Code and review | Reviewed exact adapter commit; Python, Node Plugin API and shipping bundle regressions; no unresolved relevant review findings | Synthetic results must be labelled separately from native results |
| Runtime compatibility | Supported Python matrix and the Creator native Python 3.7 aggregate gate; actual Core dependency compatibility | Syntax checking on a newer Python is insufficient; optional MCP SDK trial code requires Python 3.10+ |
| Shared deployment | Trusted shared Runtime payload, interpreter/ABI/dependency probe, isolation and adapter entry/manifest | Manifest negotiation alone cannot authorize or establish managed launch; do not build another installer |
| Native write | Approved Figma Design target, assigned development-plugin ID and existing approved pairing; discovered typed MCP apply/edit/read with actual object IDs | A test double, logical blueprint ID or an HTTP success is insufficient |
| Editable design | Actual text/fonts, local component/instance/variant relationships, Auto Layout and variables; measured desktop/mobile and state behavior | Separate source declarations, stored properties, actual layout and visual review |
| Persistence | Actual same-file save/close/reopen, then matching observed native IDs and relevant values | Reconnect, undo boundaries and version-history creation cannot substitute for this |
| Export | Actual PNG/SVG bytes and hashes; inspect/reopen exports in an intended consumer | Offline SVG/PNG rendering is separate evidence |
| Reproduction | Approved blank-page rebuild from a recorded recipe and comparison against stated tolerances | A repeated fixture or replay of an indeterminate write is not reproduction |
| Showcase | The original showcase repository's current contract, inventory, attribution, licenses, native video, localization and site checks | See [showcase acceptance](SHOWCASE_ACCEPTANCE.md); no private implementation or machine information is automatically cleared for its public tree |
| Publication | Final artifacts and archives inspected for secrets, private paths, accounts, internal assets and license obligations; exact tested head still current | No private-to-public visibility change, additional repository or package publisher |

## Unresolved native prerequisites

The latest coordinator report says the DCC-CUA Host is running, but the intended
Figma target is not exactly bound. No valid Figma target PID/HWND or task route,
assigned development-plugin ID or existing approved pairing has been established
in this adapter acceptance run. Do not repeat the historical `host_not_running`
diagnosis as the current cause.

Desktop work is serialized by the existing host coordinator. Resume through the
same supported Host only after a Figma window is available and exactly bound;
browser work must use DCC-CUA or the project's own Chrome companion, as explicitly
selected by the user. Do not substitute the GPT computer-use or Chrome route.
Do not interrupt another application's credential confirmation, start a duplicate
Host, change identity/provider/session, alter ACLs, or generate new credentials.
New pairing or permission scope still requires its specific approval.

Neither a working typed adapter nor this checklist establishes Figma entitlement,
private-use compliance, Community eligibility, managed deployment readiness or
native persistence. Release and showcase publication stay pending while their
required evidence is absent.
