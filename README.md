# AssetOS v5 — Agentic Property Intelligence

AssetOS v5 replaces v4's fixed routing pipeline with a single **agentic loop**:
a controller model observes tool results, decides the next action, and iterates
until it can answer or produce an artifact. It can research the web, browse,
delegate computer-use sub-tasks to Codex, ground itself in asset memory, and
render DOCX artifacts.

```text
User task
-> AgentLoop.run(task)
   loop (max 12 iterations):
     controller (Codex) sees system prompt + full transcript
     -> {"thought", "action": {"tool", "args"}}  or  {"thought", "final_answer"}
     -> tool executes -> observation appended to transcript
-> AgentState (answer, artifacts, turns, event_log)
```

## What changed from v4

| v4 | v5 |
| --- | --- |
| Fixed pipeline: asset -> file -> skill resolvers -> 3-step plan -> executor | One observe-think-act loop; the agent inspects memory itself and reacts to results |
| `src/routing/` (4 resolvers, plan router, validator — ~25 files) | Deleted. Replaced by `list_assets` / `read_memory` / `list_skills` / `load_skill` tools |
| `web_search` existed but was never registered | Registered, plus `fetch_url`, `browse_web`, `codex_agent` |
| Codex used as a dumb one-shot text generator | Codex also used **agentically** (`codex exec --sandbox ... --search`) for browsing, scraping, and file work — no hand-built browser automation |
| `LLMClient` dispatched on model-name string equality | Role-based: `generate_json(prompt, provider="ollama"|"codex")` |
| Planner capped at 3 non-reactive steps | Up to 12 reactive turns with error feedback and retry |

Kept (modular, unchanged): `src/memory/` (path-safe asset/file/skill access),
`src/tools/build_docx/` (Python owns DOCX layout; LLM only supplies JSON), the
untrusted-content framing for memory and web text, the Ollama/Codex adapters.

## Tools

Memory
- `list_assets` — asset ids, profile snippets, memory file names
- `read_memory` — load files for an asset (sets the active asset)
- `create_asset` — scaffold a new asset with profile.md
- `save_memory_note` — persist research/decisions for future runs
- `list_skills` / `load_skill` — reusable domain guidance

Research
- `web_search` — Tavily (`TAVILY_API_KEY`); falls back to Codex's built-in search
- `fetch_url` — full-page fetch with stdlib HTML→text
- `browse_web` — multi-page automated browsing delegated to the Codex agent (read-only sandbox, `--search`)
- `codex_agent` — open-ended computer-use sub-tasks (sandboxed shell, file edits scoped to the active asset directory, web access)

Artifacts
- `generate_invoice` — validated invoice JSON (Codex), held in run state
- `build_docx` — renders the held invoice into `Artifact/<ts>_invoice_draft.docx` + `.meta.json` provenance sidecar

## Layout

```text
src/agent/    loop.py (AgentLoop), prompt.py (system prompt + transcript)
src/tools/    base.py (ToolSpec/ToolContext/ToolResult), registry.py,
              memory_tools.py, research_tools.py, artifact_tools.py,
              build_docx/ (unchanged engine)
src/memory/   assets/, files/, skills/ (unchanged from v4)
src/llm/      client.py (role-based), adapters/ (ollama HTTP, codex CLI)
src/core/     config.py, constants.py, types.py, errors.py
src/cli/      main.py
src/outputs/  formatter.py
```


## Adaptive fact layer (v5.1)

Markdown stays canonical; structured facts are derived projections governed by
a **morphable schema the agent curates**:

```text
data/memory/schema.json                  global schema (versioned + changelog)
data/memory/assets/<id>/facts.json       per-asset facts with source provenance
```

Lifecycle: `extract_facts` derives facts from markdown per the current schema
and reports "unschema'd candidates" — recurring information with no field.
The agent calls `evolve_schema` to add a home for them (or to deprecate fields
that stay empty), then re-extracts. The schema expands, contracts, and refines
itself over time.

Python referees the morphing so it can never lock in or destroy data:
- type whitelist (string, number, boolean, date, list_of_strings)
- snake_case names, 60-active-field cap
- soft deletes only — deprecated fields keep their data and can be revived
- type changes require deprecate + new field, so history stays interpretable
- every fact carries its source file; everything is regenerable from markdown

Tools: `view_schema`, `evolve_schema`, `extract_facts`, `query_facts`, plus
`calculate` — an AST-based arithmetic evaluator (no eval) the agent must use
for all money math (GST, arrears, pro-rata).

## Memory search, fact history, staleness (v5.2)

Retrieval is now search-first:

- `search_memory(query, asset_id?)` — SQLite FTS5 full-text search over all
  asset markdown (stdlib, zero deps; LIKE fallback if FTS5 is absent). The
  index at `data/memory/index.sqlite3` is a disposable cache that refreshes
  incrementally by content hash; markdown stays the source of truth.

Facts now keep their history and know when they're stale:

- `data/memory/assets/<id>/facts_ledger.jsonl` — append-only event per value
  *change* (rent reviews, ownership changes); `facts.json` is the current-view
  projection. `fact_history(asset_id, field)` reads the trajectory back.
- Each fact stores a hash of its source file at extraction time; if the file
  changes afterwards, `query_facts` flags the fact STALE and prompts re-extraction.
- Owner details are deliberately per-asset (`owner_entity` is in the seed
  schema): different assets have different owning entities.

## Perpetual session + run journal (v5.3)

The CLI is now a REPL: each question runs a fresh inner ReAct loop, seeded
with a capped session summary (recent Q/A pairs + the active asset), so a
conversation can run indefinitely without unbounded context growth.

Every run ends with an automatic reflection step: a deterministic run journal
(task, actions, artifacts, outcome) is written to the active asset's `runs/`
folder — or `data/memory/runs/` for asset-less runs — and is picked up by the
FTS index, so future runs and sessions can search what past runs did.
Journaling is mechanical (no LLM call) and best-effort: it can never fail a run.

State therefore compounds in three layers:
transcript (working memory, per run) -> session summary (per conversation)
-> markdown/facts/journal (long-term, searchable).

## Approval gates + scheduler (v5.4)

**Approval gates.** `ToolSpec.requires_approval` pauses gated tools for a
human decision. The interactive REPL prompts y/N; library/scheduled runs deny
by default — the safe default — and the agent is instructed to adapt (draft a
recommendation instead of acting). `codex_agent` is gated today; future
send/pay/post tools get the same one-line flag.

**Scheduler.** `python -m src.cli.schedule` runs a daemon that feeds recurring
tasks (defined in `data/schedules.json`, see `schedules.example.json`) into
the same agent loop: weekly arrears checks, daily lease-expiry watch,
facts-freshness sweeps. Schedule types: interval / daily-at / weekly-on —
no cron dependency. Last-run state persists across restarts so tasks never
double-fire. Unattended runs deny gated tools and journal themselves, so
everything the scheduler does is auditable in searchable memory.

## Web interface (v5.5)

A Mike OSS-style workbench lives under `front_end/` — a completely separate
module (`src/` never imports it):

```bash
pip install -r front_end/requirements.txt
python -m front_end.server      # http://localhost:8400
```

Assistant chat with a live activity ledger (SSE), asset vault with facts +
STALE badges + memory files + artifact downloads, workflow presets, the run
journal, and a sidebar switch wiring the approval policy (gated tools denied
by default). See `front_end/README.md`.

## Run

```bash
python -m venv .venv && source .venv/bin/activate   # .\.venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
export TAVILY_API_KEY=...        # optional; Codex search is the fallback
python -m src.cli.main
```

Requires Python 3.11+, Ollama running locally (fast JSON fallback role), and a
logged-in Codex CLI (`codex login`) for the controller, structured generation,
and agentic delegation.

## Safety properties

- The **controller** runs Codex in `--sandbox read-only` with no network: it can
  only decide, not act. All actions go through registered tools.
- `codex_agent` writes are scoped to the active asset directory via `--cd`;
  `browse_web` is read-only.
- Memory files and fetched web pages are framed as untrusted data; the system
  prompt instructs the agent never to follow instructions found in observations.
- Path traversal is blocked in `FileRegistry.resolve_safe_file_path` (unchanged).
- Loop guardrails: max iterations, per-observation truncation, transcript
  budget with oldest-first trimming, one reprompt on malformed JSON.

## Testing

```bash
pytest          # 57 tests: loop behaviour, recovery, invoice->docx pipeline, memory, docx engine
```
