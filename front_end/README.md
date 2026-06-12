# AssetOS front end

A Mike OSS-style workbench for the AssetOS agent: chat-first assistant with a
live activity ledger, an asset vault (facts, memory files, artifacts),
workflow presets, and the run journal. Completely separate module — `src/`
never imports `front_end/`; delete this folder and the agent, CLI, and
scheduler are untouched.

## Run

```bash
pip install -r front_end/requirements.txt
python -m front_end.server          # http://localhost:8400
```

## Views

- **Assistant** — chat with the agent. Tool activity streams in live as a
  ruled ledger; the answer and any DOCX artifacts (download chips) follow.
- **Assets** — the vault: every asset with profile snippet, memory files
  (click to read), the facts table with STALE badges, and built artifacts.
- **Workflows** — saved instruction presets (stored in `data/workflows.json`).
  Run loads the text into the composer so you can edit before sending.
- **Runs** — the journal of every run, interactive or scheduled.

The sidebar switch **Allow gated tools** controls the approval policy for
this server: off (default), gated tools like `codex_agent` are DENIED and the
agent drafts instead; on, they may act.

Single-user by design (one session, requests serialised), matching the local
deployment model of the rest of AssetOS. Bind stays on 127.0.0.1.
