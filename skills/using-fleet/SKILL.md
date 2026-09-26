---
name: using-fleet
description: Use when running any `fleet` command — the verb surface, exit codes, porcelain output, and the store/socket environment. Triggers include "fleet dispatch", "fleet roadmap", "what fleet verb", "FLEET_HOME", "porcelain", "exit code 4", "which verbs are read-only".
---

# Using fleet

## Overview

`fleet` coordinates multi-instant efforts: it leases workspaces, dispatches worker instants, and carries their
reported status onto a roadmap. It is a python3-stdlib-only package with no third-party dependencies. `bin/fleet`
is on PATH in this repo, so every command below is typed as written.

State lives in two places and nowhere else:

| Where | What |
|---|---|
| `$FLEET_HOME` | the pool (`pool/enrolled`, `pool/leases`), dispatch records, the harvest registry, the declared golden |
| `<instant>/.fleet/` | that instant's own `roadmap.json`, `proposals.json`, `declare.json`, `review.json`, `origin.json`, `seed.txt` |

No `.md` file is ever read as state. `render` turns JSON into markdown, never the reverse.

**Announce at start:** "I'm using the using-fleet skill for the fleet command surface."

## The environment is always explicit

```bash
export FLEET_HOME=/path/to/store          # the pool and the records
export FLEET_INSTANTS=/path/to/instants   # where instant folders live
export FLEET_TMUX_SOCKET=itfleet-mine     # optional: a PRIVATE tmux server
```

A verb with neither `--home` nor `FLEET_HOME` resolves its store from the **`.fleet-root` marker** at or
above the working directory — the way `git` finds `.git` — and **refuses** when it finds none, naming the
directory it searched and what would clear it.
<!-- v2-cite: mutating-verb-names-its-store A1 -->

That refusal exists for a measured reason: before it, four mutating verbs wrote a real store under
`$HOME/.fleet` and exited 0 without mentioning it, and two of them renamed instants there.

⚠️ **Read-only verbs used to keep that `$HOME/.fleet` default**, on the ground that *"nothing is enrolled"*
is a real answer to a real question. **They no longer do.** Once a box runs more than one fleet, a
permissive read is not answering about no fleet — it is answering about a **different root's** fleet,
confidently and with a population row. So a read refuses too. The visible cost: `fleet board` in an
unmarked directory prints a refusal rather than an empty board.

Each root is one directory under `$HOME` carrying `.fleet-root`, whose declared name gives that root its
tmux server:

```
~/davis_root/.fleet-root      {"name": "davis"}     -> store ~/davis_root/.fleet,  socket fleet-davis
~/davis2_root/.fleet-root     {"name": "davis2"}    -> store ~/davis2_root/.fleet, socket fleet-davis2
```

Two roots share no record, no slot, no server and no release area. Enrolling a workspace that belongs to
another root is refused, and so is a dispatch whose instants directory points out of its own root.

**Where instants are created is still named, never derived.** `--instants-dir` or `FLEET_INSTANTS`, or the
verb refuses: `$FLEET_HOME/instants` used to be a default and it planted a dispatched child outside its
effort tree at rc=0 with every guard green, invisible until an endgame compaction could not find it.

`FLEET_TMUX_SOCKET` selects the tmux **server**. Set it before anything that could start a session:
`fleet dispatch` launches the selected Claude or Codex CLI in a session named `dt-<name>`, and on the default server that is
the one act you must never perform against somebody else's coordinator. Unset, commands see the real live
sessions — which is correct in production, because guarding a live pane is what several verbs are for.

## The verbs

Read-only. Safe to run at any time; they change nothing.

| Verb | What it answers |
|---|---|
| `fleet board` | every subject HOLDING A SLOT, and nothing else |
| `fleet status` | one subject in full, with the evidence behind its state |
| `fleet leases` | every enrolled slot and who holds it |
| `fleet peers` | which live agent sessions this fleet may address, and which are FOREIGN |
| `fleet roadmap` | milestones, readiness, blockers and pending proposals |
| `fleet brief` | what a dispatched instant needs to know about itself |
| `fleet base-check` | is this workspace positioned on the base its milestone builds on? |
| `fleet reconcile` | the arm set an external monitor reads, from the one join |
| `fleet compaction-status` | whether a compaction is holding every dispatch |
| `fleet pane-guard` | the pane contract every send and close branches on, as an exit code; keyed by `--id <todo>` or `--pane <session>` |
| `fleet seed-check` | is every live worker running the briefing that was rendered FOR it? Exits `1` on any row that is not a pass — `foreign`, a collision, `unreadable` (the check could not run) or `not-delivered` (clear it with `fleet seed-delivered`) |
| `fleet lint` | the layout matrix, the watched-source registry, the near-miss rule |
| `fleet verify` | EXECUTE every documented recipe it can vouch for, in a sandbox; the rest are reported unexecuted |
| `fleet selftest` | discover and run every suite; the tree state is always stamped |
| `fleet release-status` | what is deployed right now, since when, by whom and why |
| `fleet release-list` | every release, its state and its cut time |
| `fleet release-history` | the deploy/rollback register |

Mutating. Each has `--dry-run`.

| Verb | What it does |
|---|---|
| `fleet runtime` | read the saved runtime — the DEFAULT for dispatches that choose none; `--set claude` or `--set codex` changes it between completed runs |
| `fleet send` | deliver a message file to an owned worker after observing an empty input, idle or mid-turn |
| `fleet revive` | resume an explicit session UUID using the record’s runtime, model, workspace and configuration |
| `fleet init` | bootstrap a new instant from the layout matrix |
| `fleet dispatch` | evaluate every gate, then dispatch one worker |
| `fleet resume` | adopt an existing conforming instant; evaluates NO admission rule |
| `fleet milestone` | the coordinator puts a milestone ON the roadmap — the only way work becomes dispatchable; `--retitle <new title> --reason <why>` corrects its title in place and `--history` reads prior titles, reasons, times and actors; `--retire` drops one, `--disown` releases a claim stranded by an instant that is gone (while its record is still open, `fleet close --id <todo>` first — the dispatch and `--disown` messages name the door for the owner's state). `--retitle`, `--retire`, `--disown` and `--history` are separate operations: none combines with another or with `--title`, `--status`, `--dep`, `--evidence` or `--owner`. Earlier `--retire` and `--disown` silently ignored those extra fields; they now refuse. |
| `fleet propose` | the worker's status proposal; never a roadmap write |
| `fleet apply` | the coordinator applies a proposal; the single writer of a status. Lands the NEWEST pending row for the milestone (`--at <stamp>` picks one) and closes the earlier ones as superseded; moving a done/dropped milestone needs a pending nonterminal proposal on the coordinator's roadmap and `--reopen`, which changes the row's status |
| `fleet withdraw` | close pending proposals without applying them (`--at` for one row, `--reason` required); writes the inbox, never the roadmap |
| `fleet declare` | declare a phase, and print what the consumer now reads; `awaiting-ci` is REFUSED unless a watcher is armed or named with `--watcher` (add `pid:<n>` so the board drops the claim once that process exits); a fresh watcher renews an old claim, and a missing one is tolerated only in the 5 min after the claim (`GRACE`). `holding` needs `--reason` and lasts `--for` (default 1h, max 4h): the cap excludes it until then |
| `fleet park` / `fleet unpark` | record or clear a parked decision as structured state |
| `fleet review` | record a structured round and report the gate |
| `fleet complete` | pass the gate, then rename the folder `-complete-` |
| `fleet abort` | abandon an inflight instant, with a recorded reason; RELEASES the milestone it claimed |
| `fleet harvest` | the close-out transaction, plus the observation tick |
| `fleet close` | shut a pane this store owns and stamp the record |
| `fleet seed-delivered` | record what was actually sent to a worker's pane — the positive channel for a briefing delivered by hand into a pane (a resumed or manually started worker), which leaves nothing in argv; `fleet dispatch` puts the seed in argv itself |
| `fleet reap` | free every stale lease this base owns; name the ones it does not |
| `fleet root-init` | make a directory a fleet root: its `.fleet-root` marker, store skeleton and release area. Refuses anything that is not a directory strictly under `$HOME`, and anything already inside a root — the walk stops at `$HOME` and at the nearest marker, so either would be a root no verb could find. `--share-releases <dir>` points it at an existing release area so both roots resolve one `current` |
| `fleet enroll` / `fleet unenroll` | put an existing workspace into the pool, or take it out |
| `fleet set-golden` | declare the golden workspace; there is deliberately no fallback |
| `fleet clone` | duplicate the declared golden into a new slot and enrol it |
| `fleet release-cut` | export an immutable release from a tag and write its changelog |
| `fleet release-verify` | run both suites against a release and record the verdict |
| `fleet release-promote` | mark a CANDIDATE as RELEASED; refuses without GREEN evidence |
| `fleet release-deploy` | point `current` at a release, or at the checkout with `--dev` |
| `fleet release-rollback` | point `current` back, recording why |

Every verb's flags are on its own help, and the help is derived from the same table the parser uses — so it
cannot document one thing and accept another:

```bash
fleet dispatch --help
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | needs attention / a check failed |
| 2 | bad input |
| 3 | no capacity |
| 4 | refused by an admission rule |

`4` is the one worth recognising: it means a rule *decided against you*, not that anything broke. The message
names the blocker, what clears it, and who clears it. `1` means a checker found something that needs a human.

`fleet dispatch` has one code of its own. `5` means **not-started**: the lease was claimed and the gates passed
under the claim, then a launch step failed and was rolled back. The step might be the tmux session, the
launcher, seed delivery, or the instant tree. A failure in a check the dry-run also makes (the slot's launch
settings, the render) keeps the code the dry-run gives, so the two agree. `3` and `4` keep their meaning, and
nothing was claimed for them.

**Every dispatch says what it did on STDOUT, including one that started nothing.** A non-start prints a
`refused` row (exit 3/4) or an `error` row (exit 1/2/5), with `clears_when`/`clears_who` when the answer has
them. That includes a flag the parser refuses. After a claim it also prints `step` plus bare `left_todo_id`,
`left_instant` (a path, or `none`), `left_record` (`pending-launch`/`launched`/`none`/`unknown`) and `left_lease`
(`given-back`/`retained`), and a `remedy` sentence. A non-start never prints the success keys `todo_id` or
`instant`, so their presence means a worker started. Stderr still carries the paragraph for a human. Every dispatch, `--dry-run` included, prints
`title_as_used`: the name the verb actually used. `--title` is rewritten into one dashless camelCase field, so
`gdwsites-09240324` is used as `gdwsites09240324`. When the name differs from `--title`, a `title_rewritten`
row says so. Read `title_as_used` / `todo_id` / `instant` from the output. Never derive the child from the
title you passed. A wrapper must also keep the exit status: `fleet dispatch … | grep` discards it, and a
dispatch killed by a signal prints nothing at all. An interrupt (SIGINT) during the launch rolls back and
stays an interrupt, with no row. An interrupt during the post-launch trust watch comes after the launch is
recorded: the full rows print, `trust_screen` reads `unobserved — the watch was interrupted`, and it stays an
interrupt.

**A Claude launch can stop at the folder-trust screen, and dispatch says so.** Every dispatch or revive that starts
a pane, and every dry-run whose gates pass, prints a pre-flight `trust` row — `trusted`, `untrusted`, `unknown`, or
`not-predicted` (codex) — read-only from `<CLAUDE_CONFIG_DIR>/.claude.json` and the git layout: a folder is trusted
when a trust record sits on its canonical git root (the main worktree, for a linked one) or on the cwd or a parent
up to the git toplevel; a trusted folder above that toplevel does not count. After a real launch, a bounded pane
watch (`FLEET_TRUST_WATCH_SECONDS`, default 8, finite ≥ 0) prints `trust_screen`: `observed` (plus
`trust_screen_path` and `trust_screen_is_slot`, `yes` or `NO — … do not answer it`, and one stderr line), `none`,
or `unobserved` (check with `fleet pane-guard`). Another operator dialog prints `launch_dialog observed`. On codex
the remedy differs: the first option (trust and continue) is already selected, so Enter alone answers it — Down
then Enter quits. The exit stays `0`: the worker proceeds once the coordinator or operator answers the pane, and the board reads
BLOCKED (`15`) until then. fleet never answers the screen and never writes a Claude or codex config —
`superpowers:coordinating-instants` says how to answer it.

`fleet pane-guard` has its own codes because it is a contract for an external monitor: `0` safe, `10`
queued-text, `11` mid-turn, `12` not-claude, `13` unknown-pane, `14` indeterminate, `15` awaiting-operator.
Branch on the code before any send: `0` and `11` admit `fleet send` only when its own observation confirms an empty input; `10`, `14` and `15` refuse.
An input box is empty only when it is blank, holds a DIM (SGR 2) suggestion, or shows measured chrome such as
`Press up to edit queued messages`; any other plain text there is somebody's draft and reads `10`, even when it
looks like a suggestion (D-85). A claude pane whose input box cannot be located reads `14`, idle or busy, never `0`
or `11`; a pane nothing identifies as claude (no attributed agent and no claude chrome) reads `12`, which also refuses.

`14` means the pane is alive and nothing about it could be READ — a failed observation, not a negative one.
Treat it as wait, never as permission: before a send `14` waits, but before a CLOSE the
difference is a live pane mid-turn being torn down (`FI-7`).

`15` means the pane is showing an operator dialog — `AskUserQuestion`, the folder-trust screen (Codex 0.156's
reads `enter continue · esc quit`), or Codex's approval prompt — blocked on YOU, not on a turn that
will finish by itself (`I-16`). It reads nothing like `10`/`11`/`14`: those clear with time, this one does
not, so a coordinator that sees `15` should stop polling and go answer the pane, not wait on it. Before
this code existed a dialog fell through to `0 safe`, the same answer an idle worker gets — a scheduled
poll saw a healthy quiet pane while the worker was blocked waiting on an operator.

### Choosing a worker's runtime and model at dispatch

Each dispatch can choose its own CLI and model; nothing shared is changed:

```bash
fleet dispatch --profile "$P" --title "$T" --runtime codex                     # codex, its default model
fleet dispatch --profile "$P" --title "$T" --runtime claude --model claude-fable-5-1
```

The runtime is `--runtime` > the profile's `"runtime"` (profile.json) > the saved `fleet runtime`. The model is
`--model` > the profile's `"model"` (which applies only when its own `"runtime"` is the one chosen) > none, and
none means no model flag — the CLI's configured default. The model reaches the worker on its argv (claude
`--model`, codex `-m`); the slot's `.claude/settings*.json` and `CODEX_HOME` are never edited. Both land on the
record: `board` shows a `runtime` column (`codex`, `claude/claude-fable-5-1`), `brief` a `runtime` row, and
`revive` relaunches the same pair while `resume` adopts under the record's runtime, whatever the box says.
`--dry-run` prints the choice and where each half came from; a fleet older than the release carrying these fields
ignores the profile fields silently and has no such rows, so a missing `runtime` row means the choice was not made. A codex worker on a claude box is admitted like any
other; do not switch the box to get one.
A codex worker runs with NO approval prompts inside the workspace-write sandbox, network on (FB-110, D-45):
`dispatch`/`revive` print a `codex_policy` row with the argv and the writable roots, and `brief` repeats it. The
sandbox leaves empty `.agents`/`.codex`/`.git` mount points in those roots; `close`/`harvest --id` of a codex worker
remove them once no codex naming the root is alive, one `codex_residue` row each. Codex
workers run only in clone-shaped slots: `dispatch --runtime codex` into a linked-worktree slot (ws5's shape) is refused
with exit 4, dry-run too, so pick a clone slot with `--slot` (ws8–ws10) or run that work on claude. A codex
worker's own `pgrep`/`/proc` see only its sandbox, so the verbs that probe processes or panes (22 of them, listed in
docs/README.fleet-runtimes.md: among them `board`, `pane-guard`, `close`, `harvest`, `reap`, `seed-check` and the
`release-*` verbs) are blind when it runs them. Which roles may run on codex under that limit is an operator decision still pending
(docs/README.fleet-runtimes.md).

### Selecting the box's default runtime

`fleet runtime` reports the saved choice; an older store without a setting defaults to Claude. It is only the
default for a dispatch that chooses nothing. To change it, from a normal shell, after harvesting every worker and
stopping the coordinator:

```bash
fleet runtime --set codex
```

Start the matching coordinator CLI manually. Dispatches that choose nothing use this runtime and the CLI's
configured model. Changing back uses `fleet runtime --set claude`. A record blocks a change while `resume` or `revive`
could still act on it (an `-inflight-` folder, or an open record still holding its lease or session), and so do
held leases and live in-scope agents — a crashed worker with unfinished work included. Each blocker names the
verb that clears it (`abort`, `harvest --id`, `close` then `reap`); an aborted record, or one closed after it
completed, no longer blocks, so no review has to be recorded just to switch. Never delete a lease or edit
`runtime.json` to bypass the refusal. The operator setup is in
`docs/README.fleet-runtimes.md`.

### Delivering text to a worker

Write the complete message to a file, then use the recorded worker ID:

```bash
fleet send --id "$ID" --message-file "$MESSAGE_FILE" --dry-run
fleet send --id "$ID" --message-file "$MESSAGE_FILE"
```

The command locks that pane, checks its ownership and empty input (idle or mid-turn), pastes once,
observes the draft, sends Enter and verifies that the input box empties. Claude Code
shows a queued-message display after a mid-turn Enter and reports `queued-behind-turn`. Codex reports
`submitted-mid-turn` until its queue or steering semantics are measured. Idle delivery reports `submitted`.
Queued text, an operator dialog and an indeterminate pane refuse. If the confirmed inserted draft
remains after Enter, the command re-observes immediately before retrying Enter once; a dialog,
foreign draft or unreadable state refuses that retry. A one-round-trip race between observation and Enter
remains. It reports `inserted-not-submitted` if the same draft still remains. If delivery is uncertain, inspect the pane before another send. Never clear another draft.

**Multi-line messages are delivered whole (`FB-27`).** Both TUIs replace a large paste with a count summary —
Claude Code draws `[Pasted text #N +M lines]` for four or more lines, codex `[Pasted Content C chars]` above
about a thousand characters — and the verb confirms that summary against the message (M = its newlines,
C = its characters) before the first Enter. The text is in the box behind the placeholder; a placeholder whose
counts disagree is somebody else's paste and is never submitted. `send` prints `confirmation` as `draft`
(the text was read back), `placeholder` (the counts agreed) or `placeholder-uncounted` (Claude Code's
single-line `[Pasted text #N]`, which states no length at all), and the record says which.

**A message taller than Claude Code's input box is confirmed by its tail (`FB-134`).** The box shows only its
last rows, and its height follows the pane's. At 80 columns a 20-line pane shows 5 rows, so a one-line message
of about 400 characters no longer fits. `send` then confirms `draft-tail`. The box must show at least three
rows, and they must be exactly the message's own last rows as Claude Code wraps it at the box's own width, which
is read off the box's border (80 columns wrap at 76; only that width is measured, and a wrong one can only refuse).
A frame taken 0.1 s later must show the same rows, and tmux must report that no attached client gave the pane any
input since the send was admitted: a keystroke that lands before the paste would sit, hidden, in front of our
message. An observer client (read-only or control mode) or an attachment that cannot be read refuses too. Only
then does the verb press Enter, and Enter submits the whole message, hidden head included. What the tail cannot see
is the head, so after Enter the verb reads the transcript, where Claude Code echoes the submitted message, and
records `submitted` only when that echo is the whole message from its first word. Otherwise it records
`uncertain-after-enter`: the message was submitted, but not provably whole, so inspect the worker and never send it
again blind. `draft-tail` is recorded apart from `draft` either way. What still passes the pre-Enter check is a
head lost inside the box whose remaining rows end in the same last rows: for a two- or three-line message, losing
whole leading lines always does, and a loss inside a line often re-converges. The echo check is what reports it. Any
box whose rows are not the message's own last rows, such as a tail cut mid-word or text re-wrapped into different
rows, still ends `uncertain-after-insertion` with the text left in the box. A word wider than the box is not yet
modelled (how Claude Code breaks it is unmeasured), so such a message also ends `uncertain-after-insertion`.

**Every send that reached the pane is recorded (`B13`)** in the worker's `.fleet/sends.jsonl`: when, by whom
(`--by`, else the sender's own `FLEET_INSTANT`), the message's sha256, size and first line, the outcome
(`submitted`, `queued-behind-turn`, `submitted-mid-turn`, `inserted-not-submitted`; `uncertain-after-insertion` / `uncertain-after-enter` when the draft or its consumption could not
be confirmed; plain `uncertain` when the paste or the Enter could not be issued at all, so the pane may hold
nothing) and how it was confirmed. A refusal before the paste wrote nothing into the pane and is not a row. `fleet brief --instant <worker>` reads it
back on its `messages` row, so "who wrote into this pane" has a subject to join against. `--dry-run`
records nothing.

`fleet peers` reports runtime and address transport in human output. Use `fleet send` for owned tmux
workers. A native messaging API is usable only when the current harness exposes it and peer discovery
supplies its address; a tmux session name is not a native agent ID. FOREIGN or unaddressable peers are
not message targets.

A known agent with an unfamiliar input returns `14 indeterminate`. Every positively identified operator
dialog — Claude's folder-trust screen or `AskUserQuestion`, Codex's approval prompt — returns `15
awaiting-operator` (above), on either CLI: the advice is the same for all of them, go answer the pane. `12 not-claude` retains its legacy label and means a positively identified
non-agent pane. Treat every nonzero guard code as wait
before sending. Codex has no verified CI wake mechanism here: `awaiting-ci` is refused, even with a
watcher attestation, and the worker continues to count against capacity.

## Releasing fleet

A release is an **immutable export of a tag**, plus a verdict from both suites, plus a `current` symlink
saying which one is live. Four states: cut → verified → promoted → deployed.

```bash
fleet release-cut     --version 0.4.0 --repo "$REPO" --releases "$FLEET_RELEASES" --notes "…"
fleet release-verify  --version 0.4.0 --releases "$FLEET_RELEASES"     # both suites; ~25 min
fleet release-promote --version 0.4.0 --releases "$FLEET_RELEASES"     # refuses without GREEN
fleet release-deploy  --version 0.4.0 --releases "$FLEET_RELEASES" --reason "…"
fleet release-rollback --reason "…"    --releases "$FLEET_RELEASES"    # --to, or the register decides
```

Seven things you cannot guess, each of which cost something to learn:

1. **A cut needs a CLEAN tree.** An export carries committed content only, so a dirty tree means the
   thing tested is not the thing you edited. Refused, with the paths named.
2. **`release-verify` needs a REPOSITORY, not just the artifact.** It runs the IT suite from a
   `git worktree` at the release's tag, because the suite cannot judge an export — several cases need a
   real `.git`, and `git archive` writes none. A cut records `source_repo`; an older release needs
   `--repo`. A release that records neither is **refused**, never quietly verified against the export.
3. **A CANDIDATE is not deployable, and a promote without GREEN evidence is refused** — exit `4`, a rule
   deciding against you, not a breakage.
4. **The verdict comes from the FAIL rows in this run's own registers**, never from `run-all.sh`'s exit
   status. That script reports; it is not a gate. A release once recorded GREEN over a suite with seven
   FAIL rows because something asked it (`SI-38`).
5. **To triage a RED, read the per-runner registers** — `.release/evidence/it-RESULTS-closeout-*.tsv` —
   and never the merged `it-RESULTS.tsv`, which keeps rows from runs that did not happen this time — its
   fifth column, `origin`, marks each row `this-run:<runner>` or `carried-over`, so filter on it if you must
   open it. The
   evidence a FAIL row cites is copied into `evidence/it-cited/`, because the worktree it lived in is
   deleted when the run ends.
6. **Retention is 10 releases.** The oldest beyond that are removed at the next cut — never the deployed
   one, however old. Nothing is lost: the TAG is the durable artifact and a cut rebuilds the export.
7. **`--dry-run` exists on every mutating verb here**, and on `release-cut` it tells you the commit, the
   tag and the commit count without writing anything.
8. **A release that changes nothing either suite reads is `EXEMPT`, and `verify` returns in seconds.** A
   release is a `git archive` of the WHOLE repo — it ships `skills/`, `docs/` and the plugin manifest, and
   the deployed export is the marketplace source Claude Code loads skills from — so a docs- or skills-only
   release otherwise pays ~24 minutes to prove that `fleet/`, which it did not touch, still works.
   `release-verify` computes this before it spawns anything, and `release-promote` accepts `EXEMPT`, so
   **no `--force` and no per-release judgement call**. Four things make it safe:
   - The classifier is an **allowlist** (`fleet/src/fleet/release_scope.py`): a path is inert only because
     it matches something declared. An unrecognised path — a new top-level directory, a new script — runs
     the suites. A denylist would be fail-open and the failure would ship invisibly.
   - **`skills/using-fleet/**` is NOT inert**, because two suite call-sites read it: `test_contracts.py`
     asserts verb parity against this file in both directions, and `fleet/it/run-P.sh` copies its
     `profiles/worker` fixture. "Outside `fleet/`" is not the same as "not covered by the suites".
   - The anchor is the newest release verified **GREEN**, never the immediate predecessor and never
     another `EXEMPT` one — so a chain of docs-only releases stays anchored to code a suite actually saw.
     No anchor, or a missing anchor tag, means run the suites (the missing tag is refused outright).
   - The verdict is spelled `EXEMPT`, never `GREEN`, and cites `evidence/EXEMPTION.tsv` listing every
     changed path with its classification — so "the suites passed" and "the suites were not required"
     stay distinguishable, and the decision is re-derivable with one `git diff --name-only`.

   `--full` never exempts, and an `EXEMPT` verdict cannot promote a **minor or major** bump: a bump that
   size claims substantive change while the exemption claims the opposite.

`release-status` answers "what is live right now"; `release-history` is the append-only register of every
deploy and rollback, with who, when and why.

## Porcelain

Every observation verb takes `--porcelain` and emits tab-separated fields whose column schema is declared
data, not a formatting accident:

```bash
# what can be dispatched right now: ready, and nobody holds it ($7 title, $8 owner)
fleet roadmap --instant . --porcelain | awk -F'\t' '$1=="ready" && $8==""{print $2, $7}'
# what is waiting, and on what
fleet roadmap --instant . --porcelain | awk -F'\t' '$1=="not-ready"{print $2, $4}'
```

**Parse columns; never grep a sentence.** Checker verbs emit `kind`, `subject`, `severity`, `detail`,
`clears_when`, `clears_who`; `roadmap` appends `title` and `owner`, filled on every row about a milestone
(empty on a proposal whose milestone is not on the roadmap), then `evidence` (`$9`): each item the milestone
or proposal cites, re-resolved through the `-inflight-`→`-complete-` rename to where it is today, comma-joined,
an item that does not resolve suffixed `(does not resolve)`. `propose` refuses (exit 2) an evidence item that
does not resolve NOW — a relative path means the proposer's instant folder, an absolute one must exist, a URL
passes as-is — and `apply` refuses a row whose items stopped resolving. `milestone --evidence` is gated the
same way, relative to the coordinator's own folder, and stores each item where it is. A milestone item
written before those gates is read relative to the proposer that cited it (from the inbox's applied or
closed rows), and `owner` is printed where that instant is now, not where it was claimed.
<!-- v2-cite: evidence-resolves-at-propose-and-apply H12 --> Every milestone gets exactly one `ready` row (its
deps have landed — `owner` empty means dispatchable, non-empty means already claimed) or one `not-ready` row
(the `detail` names the blocker), plus one `pending-proposal` row per proposal waiting on it. Act on
`severity=violation`; report `severity=info`. A finished milestone, a ready one and a legitimately empty
population are `info`, and treating them as alarms is how a healthy board comes to read as red and then gets
ignored.

**The last row of `board` and `leases` porcelain is `population`** — the store or pool that was read, with
the same counts the human banner shows (`board`: `kind`=`population`, `identity`=the store; `leases`:
`lease`=`population`, `slot`=the pool, counts in the appended `note` column). An empty fleet is therefore
one row, never zero bytes, and a script can tell it from a wrong `FLEET_HOME`. Count subjects or slots by
column (`$2=="held"`), never with `wc -l` over the whole output.

`board --porcelain` columns are, in order: `identity`, `kind`, `state`, `label`, `slot`,
`milestone`, `note`, `runtime`, `session`, `server`, `nested`, `working`. The last four are appended;
the first eight retain their positions. `session` is the recorded tmux session, and `server`
is its recorded tmux socket (empty for a legacy record whose server was never measured).
`nested` lists nested agent PIDs folded into an owned or unowned pane's row, or `true` on a
separate nested process row. `fleet peers` also appends `nested`; a nested child stays
visible but is not an addressable peer. A worker with a standing parked question remains
`PARKED` while its pane is busy; the board's `working` column is true, and `status --porcelain` reports
`evidence.working=true`. A `PARKED` worker with `working=true` does not
increase the human-attention count.

## `--dry-run`

Every mutating verb has one, derived from whether the verb is read-only rather than added per verb — so the
next mutating verb anybody writes gets an interrogable form whether or not they remembered to ask for one. A
dry run evaluates every gate and writes nothing: not a lease, not a record, not a file. When the real call would
refuse, the dry run refuses too, with the same exit code and the same message.

That last sentence was false until fleet 0.6.7 (`B10`). `abort --dry-run` answered rc=0 `would-rename` for an
argv the real call refused rc=4, and by then the real call had already killed the session. Sixteen verbs had
the same shape. A dry run can still answer rc=0 where the real call exits non-zero in these cases:

- `reap`, for a lease whose release fails while executing (its claim directory cannot be removed). A
  foreign stale lease now refuses the dry run too, with rc 4, and a lease a cwd holder keeps is named, not
  counted as freeable (FB-85).
- `release-verify`, where a missing source repo is printed as `would-refuse` by design.
- The `harvest` tick with no `--id`, for its STALE rows.
- `abort` and `harvest --id` when the session's own processes cannot be attributed (no pane pids or
  parent walk). The dry run prints a `gate` row saying it could not decide. If a holder is left after the
  kill, the two verbs end differently. `abort` waits once more and names the partial state. `harvest --id`
  has already applied the proposals and stamped the record by then, so it refuses naming that partial state
  — and whatever it signalled first — and leaves the slot for `reap`.
- `abort` when a process of the session's own tree survives the kill: nothing can see that before the kill.
  `harvest --id` ends such a survivor after the kill (it is the session's own); it still refuses at the release
  if one outlives even KILL.
- `revive` on a record with no session name. `dispatch` and `resume` never write one.

For these, read the dry run's rows, not only its exit code.

`abort` and `harvest --id` also ask the pane guard `close` asks, before anything else they do (FB-88): a
mid-turn pane, one holding unsubmitted text, one awaiting an operator or one whose state cannot be read is
refused with rc 4, dry run and real alike, and the refusal names the verb's own override (`fleet abort
--instant <w> --reason <why> --force`, `fleet harvest --id <todo> --force`). That holds whether or not an agent
process is attributed to the pane: an agent's pane whose input box cannot be located is refused as indeterminate, as
`pane-guard` answers `14` for it (FB-130). A pane counts as not an agent's only on process evidence — nothing
attributed, tmux's `pane_current_command` naming no agent in any pane, and nothing claude on screen; a missing glyph
is not evidence, and an unanswered tmux fails closed. Three shapes stay closeable without `--force`: no session
answers, every pane of the session is dead by tmux's own `pane_dead` (remain-on-exit), or that process evidence says
no agent is there. `pane-guard` still reads an unattributed codex pane `12` even while it holds a draft, a turn or a
dialog; `close` refuses those, so do not read that `12` as "closeable". `--force` overrides that judgement
about work in progress and nothing else — never the cwd-holder gate. A process whose cwd cannot be read counts
as an UNDECIDED holder of a slot when it descends from one that sits there; a teardown writes such processes
into the lease before its kill, so they keep the slot held while they live (FB-90).

`close` and `harvest --id` end the slot holders ATTRIBUTABLE to the instant they tear down, and only those (V23-H):
the session's own processes that survive its kill detached from the pane (a harness watcher runs in its own session
with no terminal — so `close` of an in-flight worker also ends its detached background jobs in the slot; one still on
the pane's terminal, such as the agent still exiting from the kill, is never signalled), and a detached orphan in the
slot (parent init, its own session, no terminal, no live child outside it) that started after the worker launched,
whose environment carries that worker's `FLEET_INSTANT` and whose argv names that instant. Each one is named in a
`reaped` row (`would-reap` in a dry run, which signals nothing). A call refused before the kill signals nothing; a
`harvest` that refuses only at the release — a reaped process outlived even KILL — names every signal it sent. A holder that
names the instant, or is one of the session's own processes, but fails any of those conditions (a live child outside
it, a terminal multiplexer, …) gets its exact `kill -TERM …` line and the reason in the
refusal (or a `not-reaped` row from `close`) and is never signalled. `abort` does not reap. `complete` adds a
`watchers` row, without changing its exit code, when processes in the slot name the instant.

A dry run of `abort` or `harvest --id` can take about 2 seconds. When a process outside the session holds the
slot, it sleeps a fixed 2 seconds, as the real call does, then scans the slot once more before answering.

Use it to ask "would this be admitted?" A guard you cannot interrogate non-destructively gets interrogated
destructively — twice, by two actors, one of whom had read the entry that declined to run that exact command.

## Where the pieces live

```
fleet/src/fleet/      the package (31 verbs)
fleet/tests/          the hermetic suite
fleet/it/             the integration harness: run-*.sh, lib.sh, RESULTS.tsv, and the controls in bin/ (`it-fleet`
                      is the harness's subprocess route to the product; every runner reaches it as "$IT_FLEET")
bin/fleet             this launcher
```

`fleet/it/RESULTS.tsv` is the current verdict for every integration case — current state, not an append log.
Skills cite case ids from it, and `skills/using-fleet/tools/lint-skill.py` checks that every refusal a skill
claims names a case that actually passed.

## Related skills

- `superpowers:coordinating-instants` — you are the coordinator of an effort.
- `superpowers:working-as-a-dispatched-instant` — you ARE a dispatched worker.
- `superpowers:dispatching-subagents` — parallel work inside ONE session; not instants.
