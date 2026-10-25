# Figma login showcase acceptance and public handoff

Status: private preparation only. No showcase files have been submitted by this
review. This document records the existing showcase rules; it does not change
them, certify native production, or grant new distribution rights.

## Authoritative target and source snapshot

- Repository: <https://github.com/dcc-mcp/showcase>, public, default branch `main`.
- Public site: <https://dcc-mcp.github.io/showcase/>.
- Reviewed commit: `090d62743778b6fd0cd8bd085af4522e9caee2ff`.
- Commit date: 2026-10-22. Recheck the remote head and any matching draft before
  preparing a contribution; preserve this snapshot as the basis of this review.
- `dcc-mcp/dcc-mcp-showcase` is not the target repository.

Pinned authority:

1. [AGENTS](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/AGENTS.md)
   selects the single canonical production Skill.
2. [Production Skill](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/skills/dcc-showcase-production/SKILL.md),
   [production](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/skills/dcc-showcase-production/references/production.md),
   [acceptance](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/skills/dcc-showcase-production/references/acceptance.md),
   and [evidence](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/skills/dcc-showcase-production/references/evidence.md)
   define real production and review boundaries.
3. [Entry contract](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/docs/showcase/CONTRACT.md),
   [entry validator](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/scripts/validate_entry.py),
   [collection validator](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/scripts/validate_collection.py),
   and [collection](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/collection.json)
   govern the entry and the selected public inventory.
4. [Localization](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/docs/LOCALIZATION.md)
   governs English and Simplified Chinese presentation.
5. [Agent-data and rights](https://github.com/dcc-mcp/showcase/blob/090d62743778b6fd0cd8bd085af4522e9caee2ff/skills/dcc-showcase-production/references/agent-data.md)
   separate display, training, and evaluation permissions.

At this snapshot, the entry contract and executable validators are the submission
schema; no separate `CONTRIBUTING.md` or entry JSON Schema was found. The schema
under `benchmark/` is for benchmark planning and must not be used as an ordinary
showcase submission schema.

## Mandatory production evidence versus structural checks

For new or materially revised work, the production Skill requires actual host
work through DCC-MCP, saved-document reopening, export reopening, recipe
rebuilding, and applicable visual/media review. A structure checker cannot run
or certify any of these stages.

| Stage | Required scope and evidence for this case |
| --- | --- |
| Research and reuse | Dated visual research and bounded existing-capability/asset selection; exact source, version, hash, fit and rights for selected inputs. A later audit does not retroactively prove earlier discovery. |
| Environment | Actual Figma host, adapter, Core/gateway, plugin, fonts and relevant renderer/exporter versions or explicit unknowns. Distinguish a source commit, installed build and released version. |
| Real MCP | Actual discovered typed operation schemas, sanitized requests and responses, and observed native effects. Preserve failures and correlation in a public-safe projection. A unit-test peer, declared method inventory or successful envelope alone is insufficient. |
| Native editing | Real editable nodes, text, components/component sets, instances, Auto Layout and variable bindings for the claimed design. Record observed counts and relationships, rather than copying blueprint estimates. |
| Native layout | Inspect the actual desktop/mobile states and any claimed resizing behavior in Figma. Six separately drawn artboards do not by themselves establish responsive behavior or native constraints. |
| Save and reopen | Save/allow actual host persistence, close and reopen the same document through an approved host path, then reread the same native objects and relevant values. An undo boundary or immediate readback does not establish persistence. Do not invent a Plugin API save operation. |
| Export and reopen | Export through the real host, verify exact delivered bytes/settings, and reopen/decode PNG/SVG in the intended consumer. Offline QtSvg output is a separate artifact source. |
| Recipe rebuild | Independently reconstruct the declared result from an empty authorized document, using the recorded recipe and dependencies; compare stated counts, geometry, binding relationships and controlled output with declared tolerances. Reopening and rebuilding are separate tests. |
| Real video | Still work also needs a real viewport/process recording or consecutive native frames. A motion treatment of a static image is not native continuity evidence. |
| Review | Inspect actual final/native views and relevant intermediate outputs. Keep visual, technical, native interaction, video playback and listening scopes separate. Bind review to the delivered hashes and checked source revision. |
| Rights and privacy | Clear the selected public files, licenses, visible pixels, metadata and dependencies. A regex/hash scan alone is insufficient. |

The three mandatory entry files are:

```text
docs/showcase/<slug>/README.md
docs/showcase/<slug>/manifest.json
docs/showcase/<slug>/validation.json
```

`README.md` must present the claim title, hero, measured lead, artifact links,
supporting sections, reproduction steps and boundaries in the contract's order.
Every numerical claim must be traceable to the manifest or validation record.

`manifest.json` inventories each selected artifact with relative `path`, SHA-256
and byte count. Image records additionally need dimensions and bit depth under
the contract. Inventory only reviewed public files and hash their final public
bytes. Avoid recursive self-hashing. Mandatory metadata files do not require
their own recursive inventory entries.

The current entry validator checks presence, hashes, bytes, inventory coverage,
image limits, `validation.schema_version`, `environment`, a nonempty `checks[]`
with `name` and `result: pass|fail`, and a nonempty `not_claimed[]`. The contract
additionally requires real measured environment, counts, unit-labelled geometry
and expected/observed values for failed claims. Checks need not all pass: retain
and explain failures. Do not change `pass|fail` historical records into the
optional evidence format's different status vocabulary.

## Model, reasoning effort, source and rights

Every selected `collection.json` case needs nonempty `model_attribution` and
`revision_notes`. Required attribution stage IDs are `planning`, `creation`,
`code`, `reference`, `post_production`, plus at least one of `review`,
`review_visual`, or `review_technical`. Each row needs `stage_id`, `stage`,
`model`, `reasoning_effort`, `record_status`, `basis`, and `scope`.

Use `record_status: unknown`, `model: Unknown`, and `reasoning_effort: Unknown`
where an accepted task-configuration record was not actually checked. A model's
self-description, a filename, an ImageGen tool name or a later reviewer's model
does not establish creation attribution. `configured` requires the checked
accepted configuration and a public-safe explanation of its scope; it is not
independent backend identity attestation. `receipt_bound` is unsupported.

The case also needs dated `revision_notes` and the collection's other required
fields: public claim/summary/goal, explicitly labelled original or reusable
prompt, software/capabilities, cover/results, environment, tools, steps, checks,
limitations, resources, credits, source and verification date. Record actual
adapter/Core versions or exact unknowns. `credits` requires author, license and
note. `source.url` must be public HTTPS and pin its recorded full 40-character
commit. Use a cleared public artwork/recipe source for this field; do not expose
private adapter implementation to satisfy it or claim that private code is
publicly downloadable.

The site's MIT license covers site code, not all artwork, fonts, references or
vendor marks. Keep DCC-MCP brand rights reserved, preserve the unmodified brand
master, retain Lucide's ISC notice and Noto's OFL notice, and state the original
artwork's own display/reuse terms. Do not relabel all case assets MIT because
the adapter or site code uses MIT. Display, training and evaluation are separate
permissions; publication does not grant the latter two automatically.

## Optional records and recommendations

- `production-evidence.json` using `dcc-showcase-production/v1` is optional. It
  indexes hashed evidence and does not replace the three mandatory files,
  measurements, real traces, recipe or license notices.
- Its stage states are `passed`, `failed`, `not-tested`, and `blocked`, with
  concrete scope, evidence origin and hashed references. The template is not
  completed evidence. Its checker cannot verify model identity, licensing or
  subjective quality.
- A human may accept a narrower claim with an explicit `scope_decision`, while
  inapplicable or waived checks remain untested rather than fabricated passes.
  Intentional silence can be documented; do not invent a listening pass.
- Prefer host-native output to desktop capture. Public native-project downloads
  are case-specific, not a requirement to expose private originals. If a native
  file cannot be cleared, state that availability boundary and provide a safe
  recipe/reconstruction resource, as existing cases do.
- Use one case slug for revisions of this design. Do not count six states as six
  separate works or turn a documentation/review revision into new production.

## Current six-screen study: observed gaps

The supplied study has desktop `1440x1024` and mobile `390x844` default/error/
loading SVG and PNG pairs. Its recorded output is an offline editable design
study rendered with QtSvg, with local image inspection, pinned icon/font
provenance and unchanged brand bytes. This is useful preparation.

Its current files explicitly record `native_execution`, native resizing,
saved/reopened state and native exports as `NOT_RUN`. Logical IDs, 25 declared
components, five component sets, 30 variables and the 1,357-node expanded estimate
are offline IR facts, not observed Figma counts or bindings. The saved preflight
uses an adapter declaration rather than live discovery and reports Runtime and
typed-blueprint prerequisites unresolved. Recheck the actual updated adapter
catalog and host before a run; this historical preflight is not a permanent
statement about later adapter capabilities.

Outstanding acceptance and packaging:

1. Real typed MCP discovery and the six-screen native write/edit/readback run.
2. Measured native text/font/component/instance/variable/layout relationships,
   desktop/mobile and claimed resize checks, then same-file save/reopen readback.
3. Real host PNG/SVG export, delivered-export reopening, blank-document recipe
   rebuild, and a genuine native process video with decode/playback review.
4. A case-specific report, `manifest.json`, and contract-shaped `validation.json`.
   The existing `artifact-manifest.json` is not the mandatory filename, and the
   existing offline validation lacks `environment`, `checks[]` and `not_claimed[]`
   in the entry contract's shape. Preserve it as offline evidence rather than
   replacing its historical meaning.
5. Selected collection metadata, stage model/effort records, dated revision
   notes, public source pin, artwork rights, and English/Chinese presentation.
6. Final public-file, metadata/pixel and private-implementation review. The art
   preparation scripts contain local absolute paths; one includes a private
   machine identifier. Do not copy those scripts or the whole working archive
   into the public case without a separate cleanup/review.
7. Gallery media limits: the six individual PNGs are below `400*1024` bytes and
   at most 1440 pixels wide. `overview.png` and `contact-sheet.png` are 1800 pixels
   wide and need an inventoried derivative at most 1600 pixels wide if selected.
   `concept-original.png` is over the PNG byte limit and needs the contract's
   JPEG q82 derivative if selected. It is an ImageGen direction reference, not
   a host capture, and may instead be omitted from the minimal public package.

No actual account lookup, password handling, authentication service or running
sign-in request is claimed. A Figma design-state study does not establish a
working authentication product or physical-device testing.

## Smallest cleared public handoff

After the real production gates and rights/privacy review, select only:

1. The six final native PNG exports, with one selected as the compliant hero;
   optional native SVG exports and a compliant overview derivative, with their
   exact provenance.
2. A short real native-process MP4, with dimensions/timing/codec, full decode and
   actual playback review. The contract specifies H.264, width 1280 and at most
   60 seconds. Record intentional silence if applicable.
3. A sanitized declarative artwork recipe/blueprint and tokens, plus a public-safe
   MCP request/response and native readback summary bound to the actual run and
   output hashes. Label pre-production SVG/PNG sources separately if retained.
4. The report, manifest, validation, rights/provenance notes and required retained
   input-license notices; optional production-evidence index.

Keep private plugin/server implementation, real development manifest, pairing
secrets, credentials, raw private receipts/logs, machine/window/process details,
task/session identifiers and original private document links outside that set.
Use stable public aliases where correlation must be shown. Describe redactions;
do not synthesize missing production calls or conceal a relevant failure.
Inspect every visible image and delivered archive, not just JSON strings. Keep
private originals and sanitized public bytes separately hashed.

## Repository checks and locale acceptance

Run the current target's documented commands in an isolated reviewed checkout;
these are future publication checks, not checks performed by this document:

```sh
python scripts/validate_entry.py docs/showcase/<slug>
python scripts/test_validate_collection.py
python scripts/validate_collection.py
python scripts/test_localization.py
python scripts/test_playable.py
python scripts/test_build_site.py
python scripts/build_site.py
python skills/dcc-showcase-production/scripts/check_showcase.py --repo . --case <slug> --decode-video
```

Run other tests affected by the selected media, navigation or player changes.
`--require-ready` is an optional stricter evidence-completeness check; a true
readiness result is not artistic approval, rights clearance or native acceptance.

Complete the target's exact-string translations under English and Simplified
Chinese locale resources, including limitations, rights, unknown attribution,
alt text, errors and resource labels. Preserve evidence bytes, stable IDs,
hashes, source language and technical identifiers. Missing required translations
block the normal build.

Use the documented browser-preview workflow against the exact PR head and review
the actually served gallery/detail at desktop and mobile sizes in both locales:
links/downloads, search/filter/empty, keyboard focus, language switching, history,
media loading and natural playback. CI screenshots need human inspection.
Preview checks do not establish deployed-site behavior.

Media selected under `media/` requires the repository's Git LFS setup. Large
native/source engineering packages belong in an explicitly cleared repository
release or external resource, not in an automatically preloaded gallery bundle.
Do not install tools, create releases, upload, merge or deploy merely to satisfy
this checklist. The root task must apply its current authorizations and retain
the private adapter's visibility boundary.
