# Pre-registration: Simulation v2 of LEA on AIML101

**Status: DRAFT for the researcher's approval. Not approved. Nothing here is binding until it is
approved and committed as approved; the main run does not start before that.**

Written before the main run, after a pilot. Fields marked **[from the pilot]** are filled in
from the pilot report. The design is in `docs/simulation/PLAN.md`; this file fixes the
choices that must not change once results are seen.

## 1. Question

How well does LEA (the deployed system, unchanged) grade learners' answers, track what each
learner knows, adapt its scaffolding, recognise motivation, and write good tutor replies and
quiz items, when the learners' true knowledge is known? This is a new study on the open course
AIML101 with simulated learners. It is separate from the published results, and its
numbers are not compared with them.

## 2. What is fixed

| Item | Choice |
|---|---|
| System under test | LEA as deployed: gpt-4o-mini for tutor, grading, quiz, chat and orchestration; text-embedding-3-small for retrieval. Git commit **[record at the main run's start]**. No change to grading, mastery or adaptation. |
| Course | AIML101, KC model version 1, 63 objectives, 6 weeks; the vector store copy is hashed in each run's manifest. |
| Learners | 6 profiles × **8** learners = 48, all 6 weeks, 1 repetition **[confirm from `plan`]**. Names, parameters and the Bayesian Knowledge Tracing model as in `simulation/config/default.yaml`; objective difficulty from Bloom level plus seeded jitter; hidden engagement chain per profile. |
| Seeds | Run seed 20260925; per-learner seeds from the run seed, profile and index. |
| Simulated student | Claude Haiku (`haiku`) through a Claude subscription (`claude -p`), extended thinking off, from the tutor's actual message and the persona. Multiple choice and true/false are answered directly by the simulator. |
| Judges | Claude Sonnet (`sonnet`); second judge Claude Opus (`opus`); full model IDs pinned after the pilot **[from the pilot]**. Blind to profile, hidden state and intent. |
| Question bank | Built once with Claude Sonnet (`claude-sonnet-5`, 2026-09-25), quotes verified against the lessons, 20 entries spot-checked by the researcher. |
| External services | YouTube search is disabled in runs (LEA falls back to search links). |
| Isolation | In-process fakeredis, a per-run copy of AIML101, no writes under `data/`; simulated accounts tagged `simulated`. |

## 3. Metrics and targets

Each metric is reported whatever the result. Unit of analysis is the learner (or learner-week);
95% intervals are cluster bootstrap over learners (2,000 resamples).

| ID | Metric | Target |
|---|---|---|
| M0a | Free-text answers whose judged correctness matches the intent | ≥ 0.90 |
| M0b | Reply length, question rate and minimal-reply rate match each profile (within 20%) | all profiles |
| M0c | Simulated accuracy matches the BKT formula (10,000 draws) | within 1 point |
| M1 | Retrieval hit@k against each chat question's source lesson | ≥ 0.90 |
| M2 | RAGAS faithfulness, answer relevancy, context precision, context recall | report only |
| M3 | Follow-up questions resolved in Chat | ≥ 0.85 |
| M4 | Grading agreement with the truth (kappa; false-positive rate) | kappa ≥ 0.95 MC/TF, ≥ 0.70 other; FP ≤ 0.10 |
| M5 | Not-graded rate, warm-ups excluded | report only |
| M6 | Median Spearman rho, LEA's mastery vs the true probability of knowing | ≥ 0.5 |
| M7 | Precision of "mastered" (premature mastery = 1 − precision); recall | precision ≥ 0.85 |
| M8 | Kendall tau, order of profiles by true knowledge vs by LEA's mastery | ≥ 0.73 |
| M9 | Correlation of LEA's ZPD with true success over the last 4 graded items | ≥ 0.6 |
| M10 | Scaffolding rises within 2 turns after 2 wrong answers; falls within 3 after 3 right | ≥ 0.70 each |
| M11 | Scaffolding level changes per 10 turns while the true state is unchanged | ≤ 1.0 |
| M12 | True success probability ordered very-high < high < medium < low support, intervals separate | monotone |
| M13 | Turns per objective to mastery; share of turns on already-known objectives | report only |
| M14 | Weeks "stuck" (truly ≥ 75% known, not advanced) and "early" (advanced while < 75%) | each ≤ 0.10 |
| M15 | Macro-F1, LEA's motivation state vs hidden engagement (cold start excluded) | ≥ 0.6 |
| M16 | Tutor checklist (5 items), % yes each; reply within the length limit (375 words, LEA's `max_tokens` of 500) | ≥ 0.85 each; ≥ 0.95 |
| M17 | Coherence over the last 5 turns, 1–5 | mean ≥ 4.0 |
| M18 | Quiz item checklist (5 items), % yes each | ≥ 0.90 each |
| M20–M22 | Judge reliability: test–retest (10% sample × 3), inter-judge, judge–human (60 tutor turns, 40 quiz items, 40 chat answers) | κ or ICC ≥ 0.70, ≥ 0.60, ≥ 0.60 |

A judged metric (M0a, M3, M16–M18) is reported as a finding only if M20 and M21 (and M22 once
the researcher has labelled) meet their thresholds; otherwise it is reported with its reliability
numbers and marked unreliable. Missing judgements are counted, never imputed.

## 4. Tests

Profile comparisons use mixed-effects models (profile fixed, learner random). The
pre-registered tests, corrected together with Holm: the five adjacent-profile contrasts on
LEA's end-of-week mastery (M8), and the four adjacent-level contrasts on true success
probability (M12). Effect sizes are reported with intervals. Everything else is descriptive.

## 5. Rules

- **Complete data.** A learner-week that did not finish is marked incomplete and left out of
  the metrics that need a finished week; the count is reported. No learner is replaced.
- **Grading (M4).** Free-text answers are analysed where the fidelity check agrees with the
  simulator's intent, with a sensitivity analysis on all answers. Ungraded answers are M5, not
  errors.
- **Known LEA behaviours are findings, not exclusions.** From the pilot: LEA counts the tutor's
  opening reply as a wrong answer toward the "three in a row" rule, and grades a student's
  question or "I'm not sure" as an incorrect answer. They will show in M4, M5, M14 and M15 and
  are reported as such.
- **Budgets.** LEA's OpenAI spend is capped (`LEA_SIM_OPENAI_BUDGET_USD`). Claude use stays
  within the calibrated share of the weekly allowance and stops at any sign of overage.
- **Amendments.** Any change after approval is a dated amendment at the end of this file,
  with the reason, made before the affected results are looked at.

## 6. Known limits

Simulated learners are a model, not students: their knowledge follows Bayesian Knowledge
Tracing, and their words are written by an LLM that can be more fluent or more consistent than
people. One course. `claude -p` has no temperature or seed setting, so the student and the
judges are not reproducible turn by turn (the judges' test–retest reliability measures this).
The question bank and the judges are both Claude, though the judges see LEA's OpenAI output,
never the bank's answers. The pilot's per-learner-week costs and times, and the M0 results, are
in the pilot report.

## 7. Pilot **[from the pilot]**

Run `pilot-1`: 6 learner-weeks (one per profile, week 1), 623 turns, on the LEA commit before
the YouTube-help change. The first four learner-weeks ran with the student's extended thinking
on (about $0.93 each in API-equivalent terms); it was switched off for the rest and for the main
run (about $0.10 each). The pilot's own cost projection is inflated by those four.

**Use.** OpenAI $0.25 in the pilot (about $0.05 per learner-week). Claude, API-equivalent:
student $5.12 (559 calls), judge $5.55 (123 calls), second judge $2.91 (24 calls); no pauses,
no overage; window use at the end 17% (5 hours) and 30% (week).

**Validity (M0), not met at the pilot.** M0a 0.78 [0.73, 0.84] against a 0.90 target (the
judge-labelled correctness of free-text answers disagrees with the simulator's intent in about
one answer in five; see the pilot report for what kinds). M0b failed in 5 of 6 profiles
(advanced_eager asks fewer questions than its persona; capable_disengaged sends more minimal
replies than 0.35). M0c met (max deviation 0.008). **Before the main run, the student prompt
and persona are revised and M0a/M0b re-checked on a short second pilot; the revision is a dated
amendment here, made before any main-run result exists.**

**Projected main run (48 learners x 6 weeks = 288 learner-weeks).** Cost and run time are estimated from the
pilot's measured per-call cost and are bounded by the budgets in section 5. The scale (full judging, or half the
tutor sessions judged, chosen by seed) is fixed here before the main run.

## 8. Approval

Approved by: _______________  Date: __________  Commit: __________

## Amendment A1 (2026-09-26): comparing two cognitive-load equations

Made before any run of this comparison. Not part of the main-run pre-registration above; it governs the
two short pilots `pilot-cl-fixed` (A) and `pilot-cl-personal` (B) only.

- **Question.** Does the personalised cognitive-load equation (`src/core/cognitive_load.py`, selected by
  `lea.cognitive_load_model: personal`) track and drive support better than the fixed equation LEA has always used,
  when students' timing, typing, hint requests and relative effort ratings are available?
- **Design.** The same 12 simulated learners (2 per profile, run seed 20260925, week 1) run once under each
  equation; the equation selected drives scaffolding, and both are logged on every turn. Paired by learner.
- **Truth.** The simulator's hidden personal load (`simulation/signals.py`). It does not change whether an answer
  is right, so learning gains cannot be measured here. The personal equation's population coefficients were fitted
  on simulated students from the same generator (`fit-cognitive-load`, seed 20260927), so results are in-distribution.
- **Primary outcomes (Holm over the two).** P1: within-learner Pearson r between the load that drove scaffolding and
  the true load (higher is better). P2: share of turns whose support level is two or more levels from what the true
  load calls for, using the bands in `arms.LOAD_BANDS` (lower is better). Test: paired Wilcoxon signed-rank over
  learners; the mean paired difference is reported with a 95% cluster bootstrap interval. "Better" requires
  Holm-corrected p < 0.05 and an interval excluding 0.
- **Secondary (uncorrected, descriptive).** Mean absolute error of the driving load; over- and under-support shares;
  within-run comparison of both equations against the true load on every timed turn (`CLT.*`); the group I metrics.
- **Rules.** Learners missing from either run are left out, not imputed; an incomplete learner-week is reported.
  If the interval for a primary outcome is wide (12 learners), the result is reported as inconclusive, not as
  "no difference". Any change to the equation or coefficients after this point is a new dated amendment and a new pair of runs.

## Amendment A2 (2026-09-26): comparing scaffolding models

Made before any run of this comparison and after seeing the offline what-if on the A1 runs, which is what motivated it.
Governs the three short pilots `pilot-sc-current`, `pilot-sc-zpd_shrunk` and `pilot-sc-load_led` only.

- **Question.** Do two alternative ways of estimating ZPD and setting the support level (`src/core/scaffolding_model.py`) match
  the support a student needs better than LEA's current rules? `zpd_shrunk`: ZPD as a shrunk estimate of success. `load_led`:
  the same, plus support driven by cognitive load (raised one level when ZPD is low), ZPD steering difficulty, a run of 3 to
  fade, a two-decision hold before a level changes, and the grader also reporting whether the tutor asked a checkable question
  and its confidence (which weights the evidence; the grade, mastery and advancement are unchanged).
- **Design.** The same 12 simulated learners (2 per profile, seed 20260925, week 1) per arm; the personal cognitive-load equation
  in every arm, so only the scaffolding rules differ. Each alternative is compared with `current`, paired by learner.
- **Truth.** The hidden personal load (`signals.py`) and the learner's true recent success. The "support needed" bands are
  `arms.LOAD_BANDS` (from load) and `support_metrics.NEED_BANDS` (from recent success), fixed in advance and assumptions of this
  study. Load does not change correctness in the simulator, so learning gains cannot be measured.
- **Primary outcomes, per comparison (Holm over the two).** P2: share of turns two or more support levels from what the true load
  calls for. P3: share two or more levels from what true recent success calls for. Both lower is better; paired Wilcoxon
  signed-rank over learners with a 95% cluster bootstrap interval. The two comparisons (zpd_shrunk vs current, load_led vs
  current) are also Holm-corrected together (four tests).
- **Secondary (descriptive).** Over- and under-support against each truth; r between the ZPD score and true recent success;
  support-level reversals per 10 turns while the true state is flat; the group I metrics.
- **Rules.** As A1. In addition: a `load_led` result is reported with the grading change and the rule changes together; this
  design cannot separate them, and no claim is made about which part helped.

## Amendment A3 (2026-09-26): the motivation adjustment

Made before any run of this comparison, after the A2 runs showed why the scaffolding rules made no difference: LEA classified about
89% of turns `motivation_drop`, and that state raises the load level by one step before support is chosen (about 620 of roughly 930
"very high" decisions). In the classifier, `performance_score < 0.5` alone calls a drop, so accuracy (already what ZPD measures) is counted
as motivation, and the tutor's grader marks about half of right answers wrong.

- **Arms** (12 learners each, seed 20260925, week 1, personal load equation throughout): `control` (current rules, motivation as is);
  `support_off` (current rules; the motivation state no longer moves the load level that picks support: `LEA_MOTIVATION_SUPPORT=off`);
  `classifier` (current rules; recent accuracy no longer calls a drop or high motivation: `LEA_MOTIVATION_CLASSIFIER=no_performance`);
  `load_led_off` (the `load_led` rules with `support_off`).
- **Primary outcomes** (each arm against `control`, paired by learner; Holm over all six tests): P2 (share of turns two or more support
  levels from what the true load calls for) and P3 (the same against true recent success), both lower is better; paired Wilcoxon signed-rank with
  a 95% cluster bootstrap interval.
- **Secondary** (descriptive): M15 (macro-F1 of LEA's motivation state against the hidden engagement state), the share of turns classified
  `motivation_drop`, over- and under-support, M10a/b, M11, T1 to T3, the group I metrics.
- **Rules and limits.** As A1 and A2. The motivation state is still classified, logged and used for feedback tone in every arm; only the two
  places named above change. The classifier arm removes an input; it adds no new behavioural signal, so a large M15 gain is not expected from it.
  The student model includes the acknowledgement and short-reply fixes made after the A2 runs, so these runs are not comparable with A2's.
