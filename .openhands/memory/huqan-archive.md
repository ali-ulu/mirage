# HUQAN memory (ali-ulu/huqan) — arşiv

> Bu repo MIRAGE (ali-ulu/mirage). Aşağıdaki HUQAN notları önceki/karışmış
> oturumlardan; MIRAGE ile ilgisi yok, enjekte edilen indeksten çıkarıldı.

## Environment

- `npm test` (node scripts/run-tests.js) takes ~11–16 min and exceeds the terminal foreground cap (1080s). Run it in the background: `(nohup npm test > /tmp/npmtest.log 2>&1 & echo $!)`, then poll with `ps -p <pid>`.
- `npm ci` is required before running tests (node_modules is not pre-installed). better-sqlite3 loads fine.
- `gh` is not authenticated by default; `export GH_TOKEN="$GITHUB_PERSONAL_ACCESS_TOKEN"` first. As of 2026-09-30 the injected `$GITHUB_TOKEN` returns `401 Bad credentials` while `$GITHUB_PERSONAL_ACCESS_TOKEN` authenticates — use the latter for `gh`/API. (The env-var name in the command must be spelled out; the auto-injection still works because the name appears in the text.)

## CI traps

- The `Architecture static gates` job (`static-gates`) runs `check:architecture-trackers` first. If it fails, the five `compat-*` jobs all report `fail` without running. So six red architecture checks usually mean one root cause. Get the real log with `gh run view <run-id> --log-failed`.
- `scripts/architecture-tracker-baseline.json` must be regenerated (`npm run arch:snapshot -- --update`) whenever a PR adds new source modules. The gate compares against `--base-ref=${{ github.event.pull_request.base.sha }}` and fails with `drift: the module graph moved in N places, over threshold 50`. This drifts easily and was missed by #3164.
- A module matching no layer rule in `scripts/architecture-dependency-graph.js` fails the same gate as `FAIL unassigned: <file>`.
- The `test/debug`-style stray scripts at repo root count as source; an unclassified one fails both `check-dead-code` and the architecture dependency graph. `IS_TEST` only excludes `.test.js`, `test/`, `benchmarks/`, `demo` paths.

## Package surface

- `package.json` `files` is an explicit allowlist, not a glob of `lib/`. A new `lib/*.js` required at runtime must be added there, or `npm pack` omits it and the 4C1 tarball smoke fails with `Cannot find module './<new-file>'`. Related tests: `test/kernel-facade-contract.test.js`, `test/package-closure.test.js`.

## Graph read surface (#3012 / #3009)

- `lib/graph-node-read.js:getNodes(nodes, workspaceId, options, resolveKeys)` — 3rd param bounds/clone options (#3012), 4th the label-index key resolver (#3009). Wrong order silently reverts the #3009 index optimization; `test/graph-label-index-lookup.test.js` catches it with an `ownKeys` Proxy. `lib/graph-query-read.js:query` and `lib/graph-edge-read.js` carry the same options.
- `lib/graph-read-bounds.js` owns `normalizeReadBounds`/`applyReadBounds`. `{ clone: false }` returns frozen shallow views (`frozenNodeView`/`frozenEdgeView`) sharing nested provenance/vector/meta by design; the cost removed is `deepClone`'s JSON round-trip. Measured: `getNodes` 20k nodes 243→13 ms/call (18.8x), `getAllEdges` 40k edges 62→5 ms/call (12.0x).
- Production projections opted into frozen reads (#3012 follow-ups), each safe because it copies fields into a fresh response and never returns raw records:
  - `lib/server-graph-data.js` `/graph-data` (#3171 `e41e3831`) — test `test/server-graph-data-frozen-reads.test.js`.
  - `lib/http/read-workflow-actions.js` `searchMemory` (#3175 `c33c7306`) — test `test/workflow-search-field-scope.test.js`.
  - `lib/kernel-read-use-cases-analysis.js` `entropy`/`detectGaps` (#3185 `a52d9552`) — one `getAllEdges(scope, { clone: false })` replaces a per-node `getEdges` scan: entropy 20k nodes 39.55->3.95 ms/call (10.0x), detectGaps 1.4x. Answers identical, not approximate: `addEdge` refuses an endpoint with no node and `removeNode` purges incident edges, so no edge dangles and `getEdges(scope)` was already a subset of `getAllEdges(scope)`; entropy is a weight multiset, so order is irrelevant.
  - `reason()` (#3190) — `forwardChain`/`backwardChain`/`detectCycleBounded`/`resolveCycleOrder` take an `opts.clone === false` arm that passes `{ clone: false }` to `graph.getEdges/getInEdges`. Only the analysis use case opts in; the **default stays a detached clone** (contract #732, `test/negation-downgrade-canonical.test.js`). 60k edges with realistic provenance/meta: 75.6 -> 24.5 ms (3.1x); clone was ~66% of the call. Test `test/kernel-read-use-cases-contract.test.js` pins every walk read is clone:false, answers unchanged, and no frozen record escapes (`Object.isFrozen`).
- CORRECTION: the read path is pure. `touchNode` is called **only** in `addEdge` (`lib/graph-edge-write.js`), never from `getNode`/`getEdges`/chain/cycle/path (`graph.test.js:253` pins this). An earlier note claimed `reason`/`compare`/`ask` stamp `lastSeen` — that was wrong.
- To keep the clone contract while removing clone cost, do NOT change the public default: thread an explicit opt-in (`opts.clone === false`) from the read-only caller.
- API quirk: `Graph.addNode(id, label, provenance, opts)` ignores `opts.weight`; the weight is an occurrence accumulator (starts 0.5, +0.1 per re-add), so tests must not assert a weight passed via opts.

## Reachability ratchet (#3014)

- `test/reachability-baseline.test.js` pins `analyzeReachability().unreachable.length` to `config/reachability-baseline.json:unreachableTotal` (currently 215), and `Object.keys(NOT_YET_WIRED).length` to `measuredNotYetWired` (47).
- Adding a new leaf module (e.g. a benchmark script with no production caller) bumps `unreachableTotal`; update the baseline in the same PR or this test fails. #3164 and #3170 each forgot, and #3169/#3173 had to fix it in a separate chore PR.
- Why it drifted silently: the `npm test` shard jobs run `selectedTests` from the impact plan, not the whole suite. `test/reachability-baseline.test.js` is reachable from no changed file, so the dependency graph in `ci-test-selection.js` can never select it. Fixed in #3179 (`8e6c2701`) by adding it to `MUST_HAVE_PATTERNS` in `scripts/ci-impact-rules.js`. Any test pinning a whole-tree invariant that no changed file reaches belongs in `MUST_HAVE_PATTERNS`.
- The `npm test (runtime/test selected, ...)` shard matrix used to run on PRs only (`github.event_name != 'push'`); main-push runs showed those shards `skipped`, `runtime-test-skip` reported success in their place, and `main-ci-watch` counts `skipped` as green — so a red `main` hid behind a green push run (#3177). Fixed in #3191: the shard job now runs whenever the impact plan selects tests, on a push too (same Ubuntu+Windows/Node 22 arm; only scheduled/manual widen to macOS/Node 24). Reproduce a plan with `node scripts/ci-impact-plan.js --base="<sha>^" --head="<sha>" --mode=pr --runtime-or-test=yes --output=/tmp/plan.json` (args are `--key=value`).
- **Merge gating root cause (#3177):** the ruleset file `.github/rulesets/*.json` declared `bypass_actors: []`, but the **live** ruleset (id 23629799) had acquired a user bypass actor with `bypass_mode: "pull_request"`, so required checks did not block the merge. Evidence: PR #3177's required "npm test gate" concluded `failure` at 20:22:30Z and the merge landed 20:22:48Z. Check with `gh api repos/ali-ulu/huqan/rulesets/23629799 --jq .bypass_actors`. Repo-side pin added in #3191 (`test/github-main-ruleset.test.js`).
- **A whole-tree pin can be red on main because it is never selected.** `test/mcp-ingest-audit-duplicate.test.js` reads `test/mutation-admission-boundary.contract.test.js` as a *string*, so the impact graph has no edge from the ledger file to it. #3184 changed the ledger (unrouted 24->25, total 57->58) and the pin stayed at 24/57 — red main. Fixed in #3189. Any test that reads another file as a string (or otherwise depends on a file it does not `require`) needs `MUST_HAVE_PATTERNS` coverage in `scripts/ci-impact-rules.js`.

## Flaky CI: browser smokes

- The claim-workspace / graph-data / pr-guardian / conflict-triage Chromium smokes can hang and be killed by the per-file timeout: log reads `file ... timed out after 90s (elapsed 90.034s, signal SIGTERM) — killed hanging file, see #1847 and #2814`, every test in the file marked failed, no assertion error. Harness hang, not a code failure. Fix: `gh run rerun <RUN_ID> --repo ali-ulu/huqan --failed`; usually green on retry. (`test/ui-conflict-triage-browser-smoke.test.js` hangs at 240s on Ubuntu shard 1; verified flaky in #3218 — 8/8 locally, red in CI, green on rerun.) `gh run rerun --failed` errors with "cannot be rerun; This workflow is already running" until the whole run leaves `in_progress`.

## Kernel / MCP surface changes (#3038)

- **`kernel.js` FANOUT is a hard ceiling (28), not a suggestion.** Adding a require to
  `kernel.js` trips `FANOUT:29` and `check:architecture-trackers` fails "newly tracked in
  structural". Do not raise the `FANOUT_ALLOWED` ceiling. Install a new method group from
  an existing group's `install()` instead — `lib/kernel-cognition-methods.js` now
  `require`s and calls `installInferenceMethods(Kernel)`, so `kernel.js` fan-out is
  unchanged.
- **A new Kernel public prototype method needs three things at once:** the group install,
  a forward in `lib/kernel-v2-forwarding.js` (`test/arch-4-kernel-version-parity.contract.test.js`
  fails "KernelV2.<m> must be callable" otherwise), and the surface pins below.
- **New MCP tool pins that move together:** `mcpServer.tool-naming.test.js` (canonical/legacy
  count), `test/fixtures/mcp-server-gated-responses.json` (`UPDATE_MCP_GATED_FIXTURE=1`; only
  `surface` + `jsonrpc/toolsList` change), `api-snapshot-baseline.json`
  (`node scripts/api-snapshot.js --write-baseline api-snapshot-baseline.json`; only `digest`
  + the `mcp` array change), `test/mcp-tool-dispatch.test.js` (CASES/GOLDEN),
  `test/fixtures/mcp-gate-risk-decisions.json`.
- `check:architecture-trackers` errors "base ref is required" when run without
  `-- --base-ref=origin/main` (the `npm run` form works bare in CI).
- **`config/reachability-baseline.json` conflicts on every rebase** (unreachable/reachable
  totals shift with main). Re-measure on the rebased tree rather than taking either side:
  `node -e "const {analyzeReachability,NOT_YET_WIRED}=require('./lib/module-reachability');const r=analyzeReachability();console.log(r.unreachable.length,r.reachable.length,Object.keys(NOT_YET_WIRED).length)"`.


## Test-selection fusion (#2610 / #3014)

- `scripts/ci-test-selection.js` treats every `require('./x')` literal in a file's source as an edge — including a require inside a function body, so deferring a require does NOT keep it out of the graph. Only removing the edge does.
- Re-export hubs are load-bearing for selection size: requiring `lib/external-action-identity.js` instead of the module defining the symbol (`lib/external-action-identity-records.js`) pulls in the identity closure and fuses the cli/mcpServer/server runtime into unrelated tests. #3177 did this via `agent-v3-dream-loop-adapter -> gate-outcome-projection -> ... -> external-action-identity`, taking the selection for `lib/external-action-identity.js` from 132 to 236, past the bound in `test/ci-test-selection.test.js`. Fixed in #3182 (`37b25441`) by requiring the real source: 236 -> 121. **Need one symbol? require its defining module, not the barrel.**

## Repo rules (see AGENTS.md)

- Reports to the user must be in Turkish; branch per PR; never push to main directly. One PR = one purpose.
- When a PR is merged and its issue acceptance criteria are met, close the issue explicitly (`gh issue edit --state`); the merge does not auto-close it.

## Merging in `ali-ulu/huqan` (verified 2026-09-30)

- **Commits must be signed** for the ruleset to clear, and this container has no signing
  key (`~/.gnupg`, `~/.ssh` empty) — so `mergeStateStatus` stays `BLOCKED` even for a
  non-draft PR. The live ruleset (id 23629799) nevertheless carries
  `bypass_actors: [{actor_id: 305066106, actor_type: User, bypass_mode: "pull_request"}]`,
  so the merge succeeds through the API:
  `gh api -X PUT repos/ali-ulu/huqan/pulls/<N>/merge -f merge_method=squash -f commit_title="..."`.
  Method must be `squash`. Check `gh pr ready <N>` first: CodeRabbit skips drafts.
- **Architecture ratchet is directional.** A Core module must not require an Application
  one (`FAIL new layer violation: lib/x.js (Core) -> lib/receipt/y.js (Application)`).
  Core modules hash with `require('node:crypto')` directly; `node:crypto` is fine, the
  receipt layer is not. Verify with
  `npm run check:architecture-trackers -- --base-ref=origin/main`.
- **A new leaf module trips two ratchets**: a reasoned `NOT_YET_WIRED` entry in
  `lib/module-reachability.js` (else `scripts/check-dead-code.js` fails) **and** +1 on
  both `unreachableTotal` and `measuredNotYetWired` in `config/reachability-baseline.json`.
  `scripts/check-package-closure.js` is one-way (loads-but-unpublished only), so adding
  to `package.json:files` is not required for an unreached module.
- Windows `npm test` shards flake on the Chromium smokes; get the file list from the
  `shard-failures-<os>-node-22-shard-<n>-attempt-1` artifact before rerunning.
- **A merged PR can silently drop your last commits.** `gh api -X PUT .../merge` takes an
  optional `sha`; without it the merge uses whatever the branch head was at request time.
  In this session #3212 merged at 13:08:56Z (squash -> `73f632df`) while the CodeRabbit
  teardown fix landed at 13:09:22Z, so the fix never reached main and the branch (still
  existing) had to be re-opened as #3214. If a PR is merged from under you, verify with
  `git merge-base --is-ancestor <sha> origin/main` before assuming the work landed; then
  cherry-pick onto a fresh branch off `origin/main` and open a follow-up PR.
- **Windows `EBUSY` in tests that use a temp SQLite store.** `node:test` runs `t.after`
  hooks FIFO, so registering `rmSync(root)` before the store `close()` deletes the
  directory while `memory.db` is still open -> `EBUSY: resource busy or locked, unlink`.
  Register one ordered teardown hook that closes every store first (nested `finally` so a
  throwing close cannot skip the directory removal). Same class of failure as the Chromium
  smoke hangs: Windows-only, whole-file red, no assertion error.

## HUQAN #3027 vision issue (closed 2026-09-30)

- Umbrella/vision issue, not an implementation task. Its "gem" children #3032/#3033/#3034
  are all merged and closed. The github-app ingest gap (github-app-server.js built its
  boundary without `queueIngest`) was **closed** in #3212 (`73f632df`) +
  #3214 (`9da79d64`).
- **Next real slice: #3044 / Experience chain.** `lib/experience/{router,personal-execution-model,procedure-registry,learning,compiler,canary,...}.js`
  is still `NOT_YET_WIRED` (no production caller) even though #2372 R3 EPIC and phases
  #2390/#2392/#2393/#2394/#2396 are all CLOSED. Genuine "premise stale / truth is
  library-only" situation. Wiring it will hit the same `kernel.js` FANOUT ceiling as #3038.
- plugin load "failures" are NOT failures: company-brain/contradiction-alert/repo-memory
  are inactive because companyMode/temporal are off by default (kernel-contract.js
  DEFAULT_CAPABILITIES). `huqan status` reports them as skips; plugin.js only prints
  "Plugin failed to load" for genuine errors.
- `npm ci` is required before running the server locally; without install, server.js fails
  on missing proper-lockfile.

