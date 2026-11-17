# Simulation v2 plan: AIML101, ground-truth learners, tighter metrics

A new simulation of LEA on the open course **AIML101**, built so that its metrics measure
LEA itself and can be trusted. It is a new study, not a rerun of the published one: the
published simulation used a different course whose vector store is not released. The code of
the published study is in [tep00018/LEA](https://github.com/tep00018/LEA), tag `v1.0-snsc`.

Related work in progress: Phase 6
(`docs/teacher/BUILD_PLAN.md`), whose event log (B1) this simulation writes to as
`session_kind = simulated`.

**Who pays for what.** LEA itself (the system under test) keeps using OpenAI exactly as
deployed. Everything the simulation adds (the simulated students, the judges, the
question bank) runs on **Claude through a Claude subscription**, called
with `claude -p` on the host machine. See section 6.

## Why a redesign, not a port

The archived simulation cannot tell us how well LEA adapts. From reading the archived code:

| paper-v1 (archived code) | v2 |
|---|---|
| Tutor: learner correctness is a weighted coin flip by profile; LEA's own grading is discarded | Learners have a hidden knowledge state; LEA grades every answer; we compare LEA's grades with the truth |
| Tutor: learner replies are templates that ignore the tutor's message | An LLM plays the learner, replying to what the tutor actually said, in the profile's style |
| Tutor: the simulation re-implements the orchestrator context and mastery (0.25 + 0.15 per correct) | LEA's real services, orchestrator, grading and mastery run unchanged |
| Tutor: the feedback judge is shown the learner's knowledge level and motivation | Judges are blind to profiles and hidden states |
| The same model (gpt-4o-mini) writes and judges; failed or skipped judge calls score 0.5 or 0.7 | Claude judges LEA's GPT output (a different model family); failed calls are missing, never imputed |
| Chat (archived connector): "retrieval success" = results not empty | Retrieval checked against the lesson each question came from |
| Published CIs computed over turns as if independent (n = 5,563) | CIs by resampling learners (the real unit) |
| No seeds, no record of model versions | Seeds, a run manifest and checkpoints |
| Stratification by profile/question type was a target to hit by tuning probabilities | Differences are inputs; the metric is whether LEA recovers them |

## Principles

1. **Drive the real system.** Call the services (`src/services/`) exactly as the API does.
   The simulator may read internal state that a real student can't see (for example the
   quiz's correct answer, the retrieved chunks, orchestrator decisions), because it is the
   source of ground truth. It must never add an API route or response field that exposes
   those to clients.
2. **No behaviour change to LEA.** Nothing in `src/` changes grading, mastery or
   adaptation. If the simulator needs a hook (for example to capture retrieved chunks),
   add a no-op-by-default observer, test it, and say so in the commit. Ablations happen
   inside the simulator process only (see Arm B), never as a changed default.
3. **Never touch real data.** In-process fakeredis (as the tests do), never `REDIS_URL`
   from `.env`. A per-run copy of the AIML101 course data (Chroma rewrites its files when
   queried), so decision and motivation CSVs and the event log land in the run folder.
   Simulated usernames `sim_<profile>_<n>`; `session_kind = simulated`.
4. **Ground truth first, judges second.** Prefer metrics computed from hidden state and
   logs. Use an LLM judge only for what can't be computed, with checklists and anchored
   scales, and report a judge metric as a finding only if it passes the reliability checks.
5. **Decide the thresholds before the run.** Targets below are proposals. The researcher
   approves `simulation/PREREGISTRATION.md` before the main run, it is committed, and
   every metric is reported whatever the outcome.
6. **Reproducible.** Seeds for all simulator randomness, a manifest per run, resumable
   checkpoints, and a budget cap.
7. **Run once, analyse many times.** Every LEA exchange is saved, so judging and
   metrics can be re-run from saved events (`--rejudge`, `--reanalyse`) without calling
   LEA or OpenAI again. Tightening a rubric or a metric should never need a new run.

## Before starting

- Needs Phase 6 Part A (AIML101 is the default course) and B1 (event log with
  `session_kind`) merged. Work on a new branch, `sim-v2`, in `simulation/` (currently
  empty; the archive README already points new simulation work there).
- `simulation/runs/` is gitignored. Code, configs, rubrics, the question bank and the
  pre-registration are committed.

---

## 1. Simulated learners

### Learner model (hidden ground truth)

A Bayesian Knowledge Tracing learner per granular objective (GO):

- **Knows or doesn't.** Each GO `g` starts known with probability
  `P(L0) = sigmoid(theta - b_g)`, where `theta` is the learner's ability and `b_g` the GO's
  difficulty.
- **Learning.** After each counted tutor exchange on `g`, an unknown GO becomes known with
  probability `p_learn`; after quiz feedback on `g`, with `p_learn / 2`. No forgetting in v2.
- **Answering.** If known: correct with probability `1 - slip - d_type`. If unknown:
  correct by chance with probability `guess_type` (MC 0.25, TF 0.5, fill-in 0.05,
  open-ended 0.05, tutor reply 0.05).
- **Question-type difficulty** (an input, not a result): `d_type` = MC 0, TF 0, fill-in
  0.05, open-ended 0.10, tutor reply 0.05.
- **Session consistency.** Each session draws `eps ~ N(0, sigma)` and shifts the logit of
  "correct if known" by `eps`, so inconsistent profiles vary between sessions.
- **GO difficulty `b_g`.** From the KC model's Bloom level if present (remember/understand
  -0.5, apply 0, analyse and above +0.5), else 0; plus seeded jitter `N(0, 0.3)`. Record
  the values in the run manifest.

The true probability that the learner knows each GO is logged after every event. That is
the ground truth every tracking metric uses.

### Profiles (proposed values; the researcher confirms)

The six published names, with parameters that all change behaviour. A unit test must
show each parameter does.

| Profile | theta | p_learn | slip | sigma | Asks questions | Minimal replies | Quits a session (per turn) | Reply length |
|---|---|---|---|---|---|---|---|---|
| Advanced Eager | +1.5 | 0.30 | 0.05 | 0.1 | 0.20 | 0.02 | 0.00 | moderate |
| Moderate Reflective | +0.5 | 0.20 | 0.08 | 0.2 | 0.40 | 0.02 | 0.00 | long |
| Struggling Eager | -1.0 | 0.15 | 0.10 | 0.2 | 0.60 | 0.05 | 0.01 | short |
| Capable Disengaged | +1.0 | 0.20 | 0.15 | 0.2 | 0.05 | 0.35 | 0.08 | very short |
| Novice Variable | -1.5 | 0.12 | 0.15 | 0.6 | 0.50 | 0.10 | 0.02 | varies |
| Inconsistent Adaptive | 0.0 | 0.25 | 0.12 | 0.5 | 0.30 | 0.08 | 0.02 | moderate |

**Hidden engagement state.** Each learner also has an engagement state per turn:
`engaged`, `steady` or `disengaging`, following a small per-profile Markov chain
(Capable Disengaged spends most time `disengaging`; Advanced Eager mostly `engaged`).
The state sets the rates of minimal replies, questions and quitting for that turn. This is
the ground truth for the motivation metric (M15).

### How a learner produces a turn

1. The simulator decides the **intent** from the hidden state: an answer attempt meant to
   be correct or incorrect (from the BKT draw), a question, or a minimal reply.
2. **Multiple choice and true/false:** the simulator picks the option directly (correct
   option, or a random wrong one). No LLM.
3. **Free text** (tutor replies, fill-in, open-ended): a **student LLM** writes the text
   from the tutor's actual message, the persona (style, length, register), and:
   - intended correct: the reference answer or source passage for the GO;
   - intended incorrect: a misconception for that GO (from the question bank, below);
   - question or minimal reply: the persona only.
   It never sees LEA's internal state (mastery, ZPD, scaffolding).
4. **Fidelity check (M0).** A judge, blind to the intent, classifies each free-text answer
   as correct or incorrect against the reference. Grading metrics use the answers where
   the check agrees with the intent, with a sensitivity analysis on all answers.

The student model is Claude (default alias `haiku`, configurable), through the
subscription (section 6). That also keeps the student and the tutor from being the same
model. `claude -p` has no temperature or seed setting; the manifest records that, and
the simulator's own randomness (intent, options, engagement) stays seeded.

### Question bank (committed; built once)

`simulation/assets/AIML101/`: for every GO, 3 learner questions for Chat (one of them a
follow-up that refers back, such as "can you give an example of that?"), a reference answer,
the source lesson file, and 2–3 common misconceptions. Reuse
`data_foundation/generate_ragas_questions.py` where it fits, and seed misconceptions from
the ML-for-Beginners quiz distractors imported in Phase 6. Generate with Claude (alias
`sonnet`) through the subscription, and record the model ID and date. The researcher spot-checks 20 entries before the pilot.

---

## 2. Driving LEA

Per learner, week by week through AIML101:

1. **Chat:** one sitting of 3–5 questions from the bank for the week's GOs (including a
   follow-up), rephrased in the persona's style, sent through `ChatService.send`.
2. **Tutor:** `TutorService.start`, then `respond` until LEA ends the session or completes
   the week, the learner quits (engagement draw), or a cap of 40 turns. Then `end`.
3. **Quiz:** `QuizService.start`, answer every question, `next`, to the end.
4. **Week advance:** if LEA opens the next week, move on. If not, repeat Tutor and Quiz up
   to 2 more rounds, then move on anyway and mark the week "stuck" (metric M14).

Capture for every event: the learner's hidden state before and after, the intent, LEA's
full output (grade, score, mastery, feedback), retrieved chunks with their source files,
orchestrator decisions (cognitive load, ZPD, scaffolding level, motivation state) and
the model IDs returned by the API. Take decisions from LEA's own logs and state where
possible, not from re-computation.

**Scale (proposed).** Pilot: 1 learner per profile, week 1. Main: 8 learners per
profile (48), all AIML101 weeks, 1 repetition. If the pilot's cost estimate is too
high, reduce weeks before learners.

---

## 3. Metrics

Each metric has an ID, a data source and a proposed target. **GT** = computed from
ground truth and logs (no judge). **J** = LLM judge. Unit of analysis is the learner (or
learner-week) unless stated.

### 0. Simulator validity (must pass before the main run)

| ID | Metric | Source | Target |
|---|---|---|---|
| M0a | Student fidelity: free-text answers whose judged correctness matches the intent | J | ≥ 0.90 |
| M0b | Persona fidelity: reply length, question rate and minimal-reply rate per profile match the configured values (within 20%) | GT | all profiles |
| M0c | Learner model check: simulated accuracy matches the BKT formula (10,000 draws, no LEA) | GT | within 1 point |

### A. Retrieval and Chat

| ID | Metric | Source | Target |
|---|---|---|---|
| M1 | Retrieval hit@k: share of chat questions where at least one retrieved chunk comes from the question's source lesson | GT | ≥ 0.90 |
| M2 | RAGAS faithfulness, answer relevancy, context precision, context recall (existing pipeline, versions pinned) | RAGAS | report only |
| M3 | Follow-up resolution: the answer to a follow-up addresses what it refers back to (chat memory) | J (yes/no) | ≥ 0.85 |

M2 continues the paper's RAGAS reporting on a different course; don't compare it to the published course
as if it were the same test. RAGAS keeps its usual OpenAI evaluator (gpt-4o-mini plus
OpenAI embeddings) so its method matches the paper's; it costs about a dollar a run.

### B. Grading (LEA's own grades against the truth)

| ID | Metric | Source | Target |
|---|---|---|---|
| M4 | Grading agreement by mode and question type: accuracy, Cohen's kappa, **false-positive rate** (wrong answer marked correct) and false-negative rate | GT | kappa ≥ 0.95 MC/TF; ≥ 0.70 fill-in, open-ended, tutor; FP ≤ 0.10 |
| M5 | Not-graded rate ("couldn't grade", warm-ups excluded) by type | GT | report |

False positives matter most: they inflate mastery.

### C. Learner model tracking

| ID | Metric | Source | Target |
|---|---|---|---|
| M6 | Mastery tracking: Spearman correlation between LEA's per-GO mastery and the true probability of knowing, at the end of each week | GT | median rho ≥ 0.5 |
| M7 | Mastery decisions: precision (GOs LEA marks mastered that are truly known) and recall (truly known GOs LEA marks mastered by week end). **Premature mastery** = 1 - precision | GT | precision ≥ 0.85 |
| M8 | Profile separation: Kendall tau between the six profiles ordered by true knowledge (mean true probability of knowing at week end) and ordered by LEA's mean end-of-week mastery; adjacent-profile gaps with CIs. Replaces "response accuracy stratification" | GT | tau ≥ 0.73 (at most 2 of 15 pairs swapped) |
| M9 | ZPD tracking: correlation between LEA's ZPD value and the learner's true success probability over the same last 4 graded items | GT | r ≥ 0.6 |

### D. Adaptation behaviour

| ID | Metric | Source | Target |
|---|---|---|---|
| M10 | Scaffolding responsiveness: after 2 truly incorrect answers in a row, support increases within 2 turns; after 3 correct in a row, support decreases (fading) within 3 turns | GT | ≥ 0.70 each |
| M11 | Scaffolding stability: level changes per 10 turns while the learner's true state is unchanged | GT | ≤ 1.0 |
| M12 | Level–need alignment: mean true success probability is ordered intensive < high < medium < low | GT | monotone, CIs not overlapping for adjacent levels |
| M13 | Efficiency: tutor turns per GO until LEA mastery, by profile; share of turns spent on GOs the learner already knew (over-teaching) | GT | report |
| M14 | Week-advance accuracy: "stuck" (truly ≥ 75% of GOs known but not advanced after 3 rounds) and "early" (advanced while truly < 75%) rates | GT | each ≤ 0.10 |

M10–M12 turn the dissertation's "the CL × ZPD scaffolding is too complex" into numbers.

### E. Motivation

| ID | Metric | Source | Target |
|---|---|---|---|
| M15 | Motivation state agreement: LEA's state (`maintained_high`, `motivation_plateau`, `motivation_drop`) against the hidden engagement state (`engaged`, `steady`, `disengaging`); confusion matrix and macro-F1; `cold_start` turns excluded | GT | macro-F1 ≥ 0.6 |

Expect one known weakness to show up: LEA classifies `motivation_drop` when performance is
below 0.5, so engaged but struggling learners may be labelled as dropping. Report the
confusion matrix by profile.

### F. Tutor dialogue quality

Judged per tutor turn from the transcript and retrieved chunks only (no profile, no hidden
state).

| ID | Metric | Source | Target |
|---|---|---|---|
| M16 | Checklist, % yes for each: consistent with the retrieved course content; responds to what the student just said; explains why an answer is right or wrong; doesn't give away the answer before an attempt; ends with a clear next step or question | J (yes/no) | ≥ 0.85 each |
| M16b | Length within the course profile's limit | GT | ≥ 0.95 |
| M17 | Coherence over the last 5 turns, anchored 1–5 scale (anchors written in the rubric file) | J | mean ≥ 4.0 |

### G. Quiz items

| ID | Metric | Source | Target |
|---|---|---|---|
| M18 | Item checklist, % yes for each: answerable from the week's content; exactly one correct option (MC); plausible distractors; tests its tagged GO; stem doesn't reveal the answer | J (yes/no) | ≥ 0.90 each |

The manuscript excludes the KC Alignment subsection. M18 is for improving LEA, not for the
paper, unless the researcher decides otherwise.

### H. Judge reliability (gates every J metric)

| ID | Check | Target for the metric to be reported as a finding |
|---|---|---|
| M20 | Test–retest: a 10% stratified sample judged 3 times | kappa (yes/no) or ICC (scales) ≥ 0.70 |
| M21 | Inter-judge: the same sample judged by a second model (default Claude `opus`; for the final reported run, optionally also an OpenAI model as a cross-family check, a few dollars) | kappa ≥ 0.60 |
| M22 | Judge–human: the researcher labels a blind sample (60 tutor turns, 40 quiz items, 40 chat answers) with the same rubric | kappa ≥ 0.60 |

A J metric that fails is reported with its reliability numbers and marked unreliable, not
dropped.

---

## 4. Judge protocol

- Judge model: Claude (default alias `sonnet`; second judge `opus`), through the
  subscription. After the pilot, pin the full model names in the config so a model update
  can't change judges mid-study. Record the exact model ID of every call.
- `claude -p` has no temperature setting, so judge randomness can't be switched off.
  That is what the test–retest check (M20) measures; report it.
- **Batch to save usage.** One judge call per tutor session (the whole transcript in, a
  JSON array with one checklist per turn out), one per quiz, one per chat sitting, and one
  per session for the M0a fidelity checks. Use `--json-schema` so output is validated.
- Rubrics are versioned files in `simulation/rubrics/`, one per metric, with the
  question, the definition of yes/no (or each scale anchor) and 2 short examples each.
  Output is JSON with a fixed schema, validated; invalid output is retried once, then
  recorded as missing.
- The judge sees only what the metric needs (transcript, retrieved chunks, the item). Never
  the profile, the hidden state, the intent or LEA's internal scores.
- No default scores. Missing is missing; report counts per metric.
- The labelling sheet for M22 is exported as a CSV in random order with the judge's answers
  hidden, and imported back for scoring.

## 5. Statistics

- Unit of analysis is the simulated learner (or learner-week). 95% CIs by cluster
  bootstrap over learners (2,000 resamples). Turn-level CIs are not reported as if turns
  were independent.
- Profile comparisons: mixed-effects models (profile fixed, learner random) with
  `statsmodels`. Correct for multiple comparisons across the pre-registered tests (Holm).
- Report effect sizes with CIs, not only p-values.
- All metrics are reported, whether or not they meet their targets.

## 6. Models, cost and reproducibility

### Who runs what

| Role | Model | Paid by |
|---|---|---|
| LEA itself: tutor, grading, quiz generation, orchestrator, chat, embeddings | Unchanged (OpenAI gpt-4o-mini, text-embedding-3-small) | OpenAI key |
| RAGAS evaluator (M2) | OpenAI gpt-4o-mini + embeddings, as in the paper | OpenAI key |
| Simulated student (free text) | Claude `haiku` | Claude subscription |
| Judges (M0a, M3, M16–M18) and M20 repeats | Claude `sonnet` | Claude subscription |
| Second judge (M21) | Claude `opus` (optional OpenAI cross-check on the final run) | Claude subscription |
| Question bank (one-off) | Claude `sonnet` | Claude subscription |

Switching LEA's own model would test a different system than the one students use, so
it stays out of scope. The OpenAI spend that remains is LEA's own calls. Measure it in
the pilot; as a rough guide at gpt-4o-mini prices, a full main run should be tens of
dollars at most, and a small iteration run (2 learners per profile, 2 weeks) around a
dollar or two.

### Calling Claude through the subscription

Anthropic allows a Pro or Max subscriber to use `claude -p` (Claude Code's
non-interactive mode) and the Agent SDK in their own projects, and as of June 2026 that
usage counts against the subscription's normal usage limits. That is the only supported way
to use the subscription from code; there is no subscription-billed API key. Build a small
client, `simulation/llm/claude_cli.py`, that calls `claude -p` in a subprocess:

- **Authentication.** Before the first call, remove `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_CODE_OAUTH_TOKEN` from the subprocess environment. In
  `-p` mode an API key is always used when present, and it would bill the API instead of
  the subscription. Don't use `--bare`, because bare mode ignores the subscription login.
  Never put an Anthropic API key in `.env` for this project. At start-up, run one test call
  and stop with a clear message if it isn't using the subscription login.
- **A clean, cheap call.** `--model <alias or full name>`, `--system-prompt-file` (replaces
  Claude Code's own coding prompt with the role prompt), `--disallowedTools "*"` (no tools),
  `--no-session-persistence`, `--max-turns 1`, `--output-format stream-json --verbose`
  (so usage-limit events can be read, see below; the last line is the result), and
  `--json-schema` for judges. Use the lowest `--effort` that passes the pilot's checks
  (lowest for the student). Run it from an empty working directory under the run folder so this repo's
  `CLAUDE.md` and settings aren't loaded. Check the `system/init` event (stream-json) in a
  test and confirm no MCP servers, plugins, hooks or project memory load.
- **Record** the model ID, token usage and `total_cost_usd` for each call. Under a
  subscription `total_cost_usd` is an API-equivalent estimate, not a bill; report it as
  that.
- Default concurrency 2, configurable. Never switch to an API key automatically.
- **Windows.** Find the executable with `shutil.which("claude")`, since npm installs it
  as `claude.cmd`. Pass prompts through stdin or a temp file, not the command line, to
  avoid length and quoting limits.
- If `claude -p` proves unworkable on the host machine, the Python Agent SDK (`claude-agent-sdk`),
  signed in the same way, is the fallback. The same rules apply.

### Staying inside the subscription

Goal: the simulation never causes a charge beyond the subscription, and never uses so
much of the allowance that the researcher can't work in Claude Desktop. Four layers, because
Anthropic's own usage signals are only partly exposed to scripts.

**1. Account setting (researcher, before any run).** Paid plans can turn on *usage credits*
(formerly "extra usage"), which let work continue past the plan's limits at API rates.
With them off, hitting a limit just pauses. The researcher checks they're off in Claude's
usage settings (or with `/usage-credits` in Claude Code). The run manifest records that
she confirmed it (`usage_credits_confirmed_off: true` in the config). A run won't start
without it.

**2. Stop on any sign of overage.** In `stream-json` mode, Claude Code emits
`rate_limit_event` lines with a `rate_limit_info` object. Fields seen in practice:
`status` (`allowed`, `allowed_warning`, `rejected`), `rateLimitType` (for example
`five_hour`, `seven_day`), `resetsAt` (Unix seconds), `overageStatus`,
`isUsingOverage`, and near a limit `utilization` (0–1) and `surpassedThreshold`. These
fields aren't formally documented, so parse them defensively: log every event
to `runs/<id>/usage_events.jsonl`, and treat missing fields as unknown, not as safe.
- `isUsingOverage: true` → **stop the whole run at once**, write a checkpoint and tell the
  researcher. Never continue past this automatically.
- `status: rejected` → pause until `resetsAt` (plus 2 minutes), then resume.
- `status: allowed_warning` with `utilization` at or above the pause threshold
  (defaults below) → pause until `resetsAt`.
- Also stop at once on any error that mentions a spend limit, credits or billing.

**3. The simulation's own budgets (the dependable layer).** Every Claude call in this
project, including the question bank build (S2), goes through the one client, so it
meters all Claude use (calls, tokens and API-equivalent dollars from each result) and enforces
caps that don't depend on Anthropic's signals:

| Setting | Default | Meaning |
|---|---|---|
| `claude.per_5h_budget` | set from calibration | Max API-equivalent $ in any rolling 5 hours; pause when reached |
| `claude.per_week_budget` | set from calibration | Max API-equivalent $ in any rolling 7 days; pause when reached |
| `claude.share_of_allowance` | 0.5 | The share of the weekly allowance the simulation may use; the rest is left for the researcher's own work |
| `claude.pause_at_5h` / `pause_at_week` | 0.80 / 0.60 | Pause thresholds for `utilization` when Anthropic reports it |
| `claude.run_hours` | none | Optional hours the simulation may run, for example 23:00–07:00, so it doesn't compete with daytime work |
| `claude.max_calls_per_run` | from the sizing plan; 400 for the pilot | Hard stop, a backstop against loops |

**4. Calibration and sizing.** Anthropic doesn't publish plan allowances as numbers,
so measure them. Until calibration exists, only the pilot may run, with the 400-call cap
and the utilization thresholds as its guards.
- **Calibrate in the pilot.** The researcher notes the 5-hour and weekly percentages from
  `/usage` in Claude Code before and after the pilot (with no other Claude work in
  between). The harness records the pilot's API-equivalent spend. The ratio gives an
  estimate of the weekly allowance in API-equivalent dollars, stored in
  `simulation/config/allowance.yaml` with the date and plan. Recalibrate if the plan or
  Anthropic's limits change.
- **Size before running.** `python -m simulation plan --config <run>.yaml` estimates the
  run's Claude calls, tokens and API-equivalent cost from the pilot's per-learner-week
  figures. It compares that with `share_of_allowance × weekly allowance` and prints how
  many days and 5-hour windows the run needs. If it's too large, it proposes changes in this
  order, and it refuses to start a run that doesn't fit the researcher's limit
  (`claude.max_days_per_run`, default 7) until the config is changed:
  1. Judge a stratified sample of tutor sessions instead of all of them (for example 50%).
     Ground-truth metrics still use every session; judged metrics report CIs for the
     sample.
  2. Fewer weeks per learner.
  3. Fewer learners per profile (not below 5).
  4. Drop the Opus second judge to a smaller sample, or to the final run only.
- **Run in chunks.** A run is a queue of learner-weeks. The harness takes what fits in the
  current budget, checkpoints, waits for the next window, and continues.
- **Re-use rather than re-run.** Changing a rubric or a metric means `--rejudge` or
  `--reanalyse` on saved events. Only judge calls cost subscription usage, and there are
  no LEA or OpenAI calls.

**Tests (no network):** a fake `claude` executable that emits scripted `rate_limit_event`
lines shows the harness stops on `isUsingOverage`, pauses on `rejected` and on
high `utilization`, pauses at each budget cap, respects `run_hours`, refuses to start without
the usage-credits confirmation, and resumes correctly afterwards.

### Reproducibility

- `simulation/config/*.yaml`: profiles, BKT parameters, scale, models, seeds, budgets.
- Run manifest (`runs/<run_id>/manifest.json`): git commit and dirty flag, config hash,
  seeds, model IDs actually returned (OpenAI and Claude), Claude Code version, package
  versions, SHA-256 of the AIML101 KC model and the vector store copy, start and end time,
  OpenAI tokens and cost, and Claude tokens and API-equivalent cost.
- Seed per learner from the run seed, profile and index. Checkpoint after each
  learner-week; `--resume` continues a stopped run (including after a usage-limit wait).
- OpenAI budget cap (`LEA_SIM_OPENAI_BUDGET_USD`, default 25): stop cleanly at the cap
  and report. Also suggest the researcher sets a monthly limit in the OpenAI dashboard.
- Never print or log keys, tokens or the Redis URL.

## 7. Runs

1. **Pilot** (1 learner per profile, week 1), with the allowance calibration in section 6.
   Report per learner-week: OpenAI cost, Claude calls, tokens and API-equivalent cost by
   role (student, judge, second judge), wall-clock time, and any pauses. Then run
   `plan` for the proposed main run and report: OpenAI cost, the Claude share of the
   weekly allowance, the days and 5-hour windows it needs, and any scale-downs it
   proposes. Also M0a–M0c and 10 sample transcripts. **Stop here** and send the researcher the
   report plus the draft `PREREGISTRATION.md`.
2. **Main** (after the researcher approves and the pre-registration is committed).
3. **Human labelling** (researcher), then the final report.
4. **Arm B, optional (needs approval):** the same learners and seeds with adaptation held
   fixed (scaffolding forced to `medium`, motivation strategy fixed), done by patching
   inside the simulator process only. Compare M7, M10–M14 and M16 with the main run to
   show whether the adaptive loop makes a difference. Mark it clearly as an ablation.

## 8. Outputs

`simulation/runs/<run_id>/`: `manifest.json`, `events.jsonl` (every turn with hidden
state, intent, LEA output and decisions), `judgements.jsonl`, `metrics.json`, `metrics.csv`,
`labelling_sheet.csv`, the copied decision and motivation CSVs and event log, and
`report.md` with one table per metric group (value, 95% CI, target, met or not, judge
reliability where relevant) and a few figures (mastery tracking scatter, scaffolding
level against true need, motivation confusion matrix).

## 9. Milestones (commit after each; all tests green)

| # | Milestone | Done when |
|---|---|---|
| S0 | Skeleton, config, isolation, manifest, Claude CLI client | A test proves a run can't reach `REDIS_URL` or write under `data/`; tests show the client strips Anthropic keys from the environment; the usage-guard tests in section 6 pass; one live call through the subscription succeeds |
| S1 | Learner model and profiles | Unit tests for BKT, M0c, and every parameter changing behaviour |
| S2 | AIML101 question bank | Committed; researcher spot-check done |
| S3 | Chat, Tutor and Quiz drivers, capture, student LLM | End-to-end test with the scripted fake LLM (no network) |
| S4 | Judges, rubrics, reliability sampling, labelling sheet | Schema validation and no-fallback tests |
| S5 | Metrics, statistics, report | Each metric tested on synthetic logs with known answers |
| S6 | Pilot | Report sent; **stop for researcher approval** |
| S7 | Main run, labelling, final report | Report shows every metric with CIs and reliability |
| S8 | Arm B (optional) | Only after approval |

Also: `simulation/README.md` (how to run, costs, outputs), `CHANGELOG.md` entry, and a
short `docs/SIMULATION.md` linking here.

## 10. Definition of done

- The main run on AIML101 completed within budget, with the manifest, events and report.
- Every Claude call went through the subscription (no Anthropic API key used), no
  usage-credit (overage) use was recorded, the run stayed within its configured share of
  the allowance, and `--rejudge` and `--reanalyse` work from saved events without any LEA
  or OpenAI calls.
- Every metric reported with CIs; every judge metric with its reliability; anything that
  failed its target listed plainly.
- No change to LEA's grading, mastery or adaptation; the archive untouched; no simulated
  data in real Redis, `data/`, research CSVs or analytics.
- All backend and simulation tests pass; nothing pushed anywhere unreviewed.

---

## Appendix: notes for the manuscript (researcher)

- Report v2 as a new study on AIML101 with this protocol, separate from the published
  published results. Don't merge or directly compare the numbers.
- Points about the paper-v1 method, from reading the archived code. Check them against the
  code that produced the published runs before relying on them; the archived Chat and
  Quiz simulation scripts are incomplete.
  - Tutor-mode learner correctness was sampled from profile probabilities, and LEA's own
    grading wasn't used.
  - The feedback-adaptation judge was shown the learner's knowledge level and motivation.
  - The judge was the same model family as the generator, and CIs were computed over turns.
  - The ICAART paper's Table 2 describes Multi-Turn Effectiveness as "mean cosine
    similarity between learner input and tutor response", but the code and the results
    text use an LLM-as-judge coherence score. Align the extended paper's description.
