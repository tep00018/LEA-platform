# Pilot report (pilot-1)

**Status: partial.** The pilot stopped at its 400-Claude-call cap after 4 of 6 learner-weeks, before
`inconsistent_adaptive` and the last learner-week of `novice_variable` finished, and before any judging. Nothing
went wrong beyond that: the guard worked as designed, and every figure below is from what ran. The cap was too low
because of a cost problem found in this pilot (section 3), not because of a fault.

Run: `simulation/runs/pilot-1` (gitignored) at commit `e18e5f9`, Claude Code 2.1.282–2.1.283, LEA on gpt-4o-mini
and text-embedding-3-small, students on `claude-haiku-4-5-20251001`. Learners: one per profile, week 1 of AIML101.

## 1. What ran

| Learner-week | Profile | Rounds | LEA mastered / truly known (of 10 GOs) | Opened week 2? | Student calls | OpenAI $ |
|---|---|---|---|---|---|---|
| sim_advanced_eager_0 | Advanced Eager | 3 | 6 / 10 | no | 78 | 0.038 |
| sim_moderate_reflective_0 | Moderate Reflective | 3 | 5 / 10 | no | 77 | 0.039 |
| sim_struggling_eager_0 | Struggling Eager | 3 | 3 / 7 | no | 126 | 0.069 |
| sim_capable_disengaged_0 | Capable Disengaged | 3 | 5 / 9 | no | 19 | 0.016 |
| sim_novice_variable_0 | Novice Variable | 2 (stopped) | not finished | – | 100 | 0.054 |

## 2. Costs measured

| | Pilot | Per finished learner-week |
|---|---|---|
| Claude calls (all student, Haiku) | 400 | about 100 |
| Claude API-equivalent cost | $4.92 (an estimate under a subscription, not a bill) | $1.23 |
| OpenAI (LEA's own calls) | $0.215 (1,595 calls, 760k tokens) | $0.04 |
| Wall-clock | 3.0 h | 35 min (mostly waiting on Claude) |
| Pauses / overage | none / none (`isUsingOverage` false on all 400 events) | |

**Allowance calibration.** Claude's own utilization, logged on every call, went from 0.01 to 0.14 (5-hour window)
and 0.25 to 0.26 (weekly) over the 3 hours. That gives about **$37.85 of API-equivalent use per full 5-hour window**
and about **$490 per week**; the weekly figure rests on a 1-point movement, so treat it as good to a factor of about
two. The researcher's `/usage` readings (before 0% / 25%, after 2% / 20%) were taken after the 5-hour window reset and
while older usage left the rolling week, so they were not used. Saved in `simulation/config/allowance.yaml`; the plan
name there is still "unknown".

## 3. Finding: the student's hidden reasoning was 90% of the cost

Haiku spent about 2,250 output tokens per call, nearly all hidden reasoning, to write replies of about 30 tokens
(mean 27 words), even with `--effort low`. That was about $4.5 of the $4.92 and about 20 s a call. Extended thinking is now
switched off for the student (`claude.student_max_thinking_tokens: 0`, passed as `MAX_THINKING_TOKENS`). A live check on
the same prompt: **$0.0009 and 2.6 s with it off, against $0.007–0.018 and 13–21 s on**, about 10x cheaper and 6x
faster. Judges keep the model's default. The pilot's own student figures therefore overstate the main run's; the
projection below uses the measured thinking-off cost. Whether thinking-off changes the student's quality will show in
M0a once the judges have run.

## 4. Simulator validity

| | Result |
|---|---|
| **M0c** learner model vs BKT formulas | met: largest deviation 0.008 (target 0.01) |
| **M0b** persona fidelity | strict rule "not met", but every target rate lies inside its 95% interval; the rule is too tight for 17–120 turns per profile (see decision 4). Reply lengths match: 24.8 words (target 25), 65.7 (60), 10.6 (10), 4.2 (4) |
| **M0a** student fidelity | not available (needs the judges) |

## 5. Preliminary readings of LEA (4 learners: descriptive, none of this is a finding)

- **Week never opened.** No learner reached week 2 within 3 rounds, though Advanced Eager truly knew all 10
  objectives and LEA marked 6 mastered. Thresholds range 0.60–0.85. M14 "stuck" 3 of 4.
- **LEA grades a student's question as an answer.** 153 of 155 student questions in tutor sessions were graded, and 4
  were marked correct. Nothing was changed in LEA; this is how it behaves, and it pulls mastery down for
  question-heavy profiles.
- **Raw grading agreement on tutor replies is 61%** (false negatives 50%, false positives 18%), but this is not
  interpretable yet: many "meant correct" replies don't answer anything (the tutor's message often asks no content
  question). The M0a fidelity judge exists to filter these, and hasn't run. Multiple choice and true/false grading agreed
  100% (61 and 28 answers); fill-in 93%, open-ended 65%.
- **Tutor replies are long:** 69.5% within 375 words (target 95%). Retrieval hit rate 0.88 on 17 chat questions
  (target 0.90, CI 0.76–1.0).
- Scaffolding and motivation metrics (M9–M12, M15) are far below target on this small sample; they will be
  reported in full at the main run.

Ten sample transcripts (with the hidden state shown for the researcher only) are in `pilot-1/transcripts/`.

## 6. Projection for the main run (8 learners per profile = 48, six weeks, 288 learner-weeks)

Student cost is the measured thinking-off figure ($0.0009 a call, 100 calls a learner-week). **Judging has not been
measured**: it is estimated from the pilot's real judge units (about 13 calls and $0.56 per learner-week for the main
pass; sonnet cost fitted to the 22 question-bank calls, residual under $0.001), plus 20% for the reliability
repeats and a 10% Opus sample at an assumed 1.7x the sonnet price.

| Scenario | Claude API-equiv. | Share of weekly allowance | Days at a 50% share | 5-hour windows | OpenAI |
|---|---|---|---|---|---|
| As proposed, all tutor sessions judged | $248 | 50% | **8 (doesn't fit 7)** | 14 | about $12 |
| **Judge 50% of tutor sessions** | $169 | 34% | 5 | 9 | about $12 |
| Judge 50%, five weeks | $141 | 29% | 5 | 8 | about $10 |
| All judged, four weeks | $165 | 34% | 5 | 9 | about $8 |

OpenAI for the main run is about $12 (range $10–20 by profile) plus about $1 for RAGAS; **a top-up is needed** (the
balance was $5.39). Wall-clock is about 16 min a learner-week if run one at a time (about 77 h), which the weekly
allowance, not the clock, limits.

Caveats: the weekly allowance is coarse (factor of two either way); the run shares the allowance with the researcher's own
Claude use, and the 0.60 weekly-utilization pause counts both; it may well pause earlier than the table implies.

## 7. Decisions needed

1. **Complete the pilot properly?** Recommended: a fresh `pilot-2` with the corrected settings, one learner per
   profile, week 1, judges and reliability samples included, with the call cap raised to 1,500. About 600 student calls
   ($0.6) plus about 77 judge calls (roughly $4), so about $4–5 API-equivalent (10–13% of a 5-hour window) and about
   $0.25 of OpenAI. It measures judging cost, M0a, M3, M16–M18 and their reliability, and gives a clean calibration.
2. **Your Claude plan** (Pro or Max 5x/20x) for `allowance.yaml`.
3. **Main-run scale**: as proposed doesn't fit 7 days; judging half the tutor sessions does.
4. **M0b rule**: replace "within 20%" by "target inside the 95% interval, or within 20%".
5. **M16b length limit**: AIML101 sets none; I used LEA's own cap of about 375 words.
6. **LEA behaviours** above (questions graded, week never opening, long replies): report as findings, or discuss
   before the main run. No change to LEA has been made.
