# Simulation v2 (AIML101)

A simulation of LEA on the open course AIML101 with ground-truth learners, built so its
metrics measure LEA itself. The design, metrics and targets are in
[`docs/simulation/PLAN.md`](../docs/simulation/PLAN.md). The code of the published
study is in [tep00018/LEA](https://github.com/tep00018/LEA), tag `v1.0-snsc`.

## Who pays for what

| Role | Model | Paid by |
|---|---|---|
| LEA itself (tutor, grading, quiz, orchestrator, chat, embeddings) | unchanged: OpenAI gpt-4o-mini, text-embedding-3-small | OpenAI key (`.env`) |
| Simulated students (free text) | Claude `haiku` | Claude subscription |
| Judges, and their repeats | Claude `sonnet` | Claude subscription |
| Second judge | Claude `opus` | Claude subscription |
| Question bank (built once, committed) | Claude `sonnet` | Claude subscription |

Claude is called only through `claude -p` (`simulation/llm/claude_cli.py`), signed in
with the subscription (`claude auth login`). The client strips every `ANTHROPIC_*` and
`CLAUDE*` variable from the subprocess, requires `apiKeySource: "none"` on every call,
and never falls back to an API key. Never put an Anthropic API key in `.env`.

## Staying inside the subscription

- **Before any run**, turn usage credits off in Claude's usage settings (or
  `/usage-credits` in Claude Code) and set `usage_credits_confirmed_off: true` in the run
  config. No run starts without it.
- Every call is metered in `simulation/runs/usage_ledger.jsonl` (API-equivalent dollars:
  an estimate under a subscription, not a bill). A run stops at once if Claude reports
  usage credits in use, pauses on a usage limit or when a window reaches its threshold
  (`claude.pause_at_5h` 0.80, `claude.pause_at_week` 0.60), and pauses at its own rolling
  budgets, call cap and optional `run_hours`.
- **Calibrate with the pilot.** Note the 5-hour and weekly percentages from `/usage`
  before and after the pilot, with no other Claude work in between (this includes Claude
  Code and Claude Desktop sessions: they share the same allowance), then
  `python -m simulation calibrate`. Until then only a pilot may run.
- **Size before running** with `python -m simulation plan`; a run that needs more than
  `claude.max_days_per_run` days of the allowed share won't start.

## Running

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[sim]"                                        # mixed models and figures (optional)
python -m simulation check-claude                             # one call: is the subscription login working?
python -m simulation build-bank --dry-run                      # the question bank (already built and committed)
python -m simulation run --config simulation/config/pilot.yaml --run-id pilot-1
python -m simulation run --config simulation/config/pilot.yaml --run-id pilot-1 --resume   # after a stop
python -m simulation judge --run-id pilot-1                    # judges, from saved events
python -m simulation reanalyse --run-id pilot-1                # metrics and report, no model calls
python -m simulation transcripts --run-id pilot-1 --n 10       # sample transcripts for reading
python -m simulation calibrate --run-id pilot-1 --plan "Max 20x" --before 43,24 --after 55,27
python -m simulation plan --config simulation/config/main.yaml --from pilot-1
```

## Trying LEA on another model

`python -m simulation compare-models` runs one scripted learner (a chat question and its
follow-up, three tutor turns, a full week-1 quiz answered right, wrong, right, wrong...)
against LEA twice: as deployed (OpenAI) and with the same services answered by Claude
Sonnet through the subscription (`simulation/llm/openai_compat.py`, an OpenAI-shaped
client injected through `build_services`; nothing in `src/` changes, and LEA's default
stays OpenAI). It writes a side-by-side `comparison.md`. It is a look at what each model
writes (one learner, one script), not a measurement; embeddings stay on OpenAI. A Sonnet
session is about 20 Claude calls. Deploying LEA on Claude would need the Anthropic API,
not the subscription, and would be a **(research)** change to LEA.

## Isolation

A run never touches real data: it runs on in-process fakeredis (a real Redis connection
raises), a per-run copy of the AIML101 course data (`LEA_DATA_DIR`), and its own event
log; any write under the repository's `data/` folder raises. LEA's code is unchanged: the
simulator calls the services exactly as the API does and reads what it needs (mastery,
retrieval, the orchestrator's logged decisions, OpenAI usage) from inside the process.
Simulated accounts are `sim_<profile>_<n>`, tagged `simulated`.

## Outputs

`simulation/runs/<run_id>/` (gitignored): `manifest.json` (commit, config and its hash,
seeds, model IDs, versions, hashes of the KC model and vector store, costs),
`events.jsonl` (every exchange with the hidden state, intent, LEA's output, decisions and
retrieval), `judgements.jsonl`, `metrics.json`, `metrics.csv`, `report.md`, figures,
`labelling_sheet.csv` (for the researcher's blind labels, M22; its key is in a separate file),
the run's decision and motivation CSVs and event log, and `checkpoint.json` for
`--resume`.

## Costs (rough)

The OpenAI spend is LEA's own calls, measured in the pilot (a few cents to a couple of
dollars per learner-week at gpt-4o-mini prices; `openai.budget_usd` caps a run). Claude use
is measured in API-equivalent dollars and sized against the calibrated allowance.
