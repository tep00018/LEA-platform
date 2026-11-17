# Status: simulation work wrapped up, ready for testing by hand

This round ends the simulation/pilot phase and sets LEA up for testing by hand instead.
No more simulation or pilot runs happened after the smoke-run comparison below; everything
past that point is either a default flip validated by that comparison, or plumbing
(test account, trace script, docs) with no research claim attached.

## What changed this round

**The tester configuration is now the default**, in `src/core/scaffolding_model.py`:

- `LEA_TUTOR_RECORDED_QUESTION` defaults to `on` (was `off`): the tutor is instructed to end
  each message on exactly one checkable question about the current objective, state only
  facts the passage supports, and keep replies short; a separate extraction call at grading
  time (not generation time, so no added latency on the tutor's own turn) finds that
  question and confirms it's about the current objective before grading against it.
- `LEA_TUTOR_QUESTION_SCOPE` defaults to `broad` (was `strict`) *(research)*: a question that
  connects or compares the current objective with another concept now also counts as "about
  this objective," instead of only a question narrowly about it. Both remain overridable
  back to `off`/`strict` via the env var.
- support_off (`LEA_MOTIVATION_SUPPORT=off`) and the V5 grader were already the defaults
  from earlier rounds; unchanged here.
- `LEA_SCAFFOLDING_MODEL`, `LEA_COGNITIVE_LOAD_MODEL` and `LEA_MOTIVATION_CLASSIFIER` are
  left at their original settings -- the app doesn't capture reply timing yet, which the
  `load_led` scaffolding model and the personal cognitive-load model both want.

**Evidence for the two flips above**, from a same-day smoke-run comparison (temperature 0.7
vs. 0.4, default settings otherwise, ~100 tutor messages per run):

- *Contradiction rate.* n=100 at 5% is too small to distinguish from a 3% target (a 95%
  Wilson interval of about 2-11%). Re-run over every tutor message in both runs found a
  full-scale rate of about 5.5%, with no clear difference between temperature 0.7 and 0.4 on
  contradiction rate, "responds to student," or mean reply length -- so temperature stays at
  0.7 (`LEA_TUTOR_TEMPERATURE`, still overridable).
- *Ungraded rate.* The smoke run showed about 28% of tutor turns ungraded. Re-running
  extraction offline with the week's full GO list to see how much of that was "not about
  this objective" (about 22 of the 28 points) found it split into: some about another GO in
  the same week, some a comparison with a related concept that should reasonably count for
  the current GO, and the rest genuinely outside the week. Broad scope (above) now credits
  the "related concept" share of that split; the "another GO in the same week" share is the
  `credit_other_go` open item below, deliberately not built this round.

**Flutter**: a tutor reply that isn't the warm-up but still couldn't be graded (e.g. no
valid recorded question about the current objective) now shows a **"Not counted"** chip
under the student's bubble, distinct from "Warm-up · not counted" -- previously it showed no
chip at all. See [tutor_header.dart](../app/lib/screens/tutor/tutor_header.dart)'s
`ReplyTagChip.notCounted` and its widget test in `app/test/tutor_screen_test.dart`.

**[scripts/session_trace.py](../scripts/session_trace.py)**: a turn-by-turn trace (time,
question, reply, graded/correct, cognitive load, ZPD, support level, motivation state,
objective mastery) for a username and course, reading only the event log and decision-log
CSVs -- no model calls. See [TESTING.md](TESTING.md).

**Test accounts**: an account flagged as a test account (session_kind `test`) never reaches the
research CSVs or `export_events.py`'s export, so testing by hand is safe. See [TESTING.md](TESTING.md).

## 2026-09-28 addendum: a quiz code-question false premise

Hand testing (not simulation) found AIML101's Week 1 quiz building a "Weak AI vs Strong AI"
question around two toy Python functions and keying the expected answer to calling the
second one "Strong AI" -- a false premise, since neither function demonstrates general
intelligence or consciousness. A correct answer that said so was marked wrong. Fixed:

- `allows_code` is now `false` for AIML101 (`data/course_profiles/AIML101.json`). A scan of
  every pilot and smoke run's saved quiz items (`simulation/runs/*/events.jsonl`, no model
  calls) found 423 of 4,330 quiz turns contained code, and every one of them was this same
  objective (`GO_01_01_004`, "Compare Weak And Strong Ai") -- nowhere else. See the open item
  below for a finer, per-GO rule instead of this course-wide gate.
- The quiz generation prompt (`src/quiz/simple_quiz_system.py`) now also says never to build
  a question (or its expected answer) on a premise the course content doesn't support, and
  never to use a toy code example to stand in for something code can't actually demonstrate.
- The V5 grader now marks an answer correct, and says so in the feedback, when the student
  correctly points out the question's own premise or example is flawed -- unit-tested only,
  not re-run through the offline replay.

## To do now (added 2026-10-12, from a code audit)

- [x] **Cross-origin PUT** (fixed 2026-10-12). The CORS allow-list was GET, POST and DELETE
  only while the Flutter client uses PUT and PATCH; the preflight was reproduced failing in a
  test and `src/api/app.py` now allows both. Not yet confirmed in a real browser session.
- [ ] **Question bank.** All 67 AIML101 reference entries are `tagging.reviewed: false`, so
  reviewed-bank mixing in Quiz serves nothing yet. Review and tag the entries.
- [ ] **Long-term memory and unused tools.** Long-term memory is written by the
  consolidation worker but never read; the academic-calendar and web-search tools are
  registered but have no call site. Either wire them in or remove them and the claims about
  them.
- [ ] **Timing data.** Neither client sends the `timing` block, which is what keeps the
  personalised cognitive-load model (and `load_led` scaffolding) off. See "Flutter timing
  capture" under Open items.
- [x] **Stale docs** (fixed 2026-10-25). `docs/ARCHITECTURE.md` (Flutter and the Teacher
  area are built; long-term memory is not read; which tools are used; module-leader services
  added), the recorded-question "off by default" wording in `CHANGELOG.md`, `docs/API.md`
  and the `scaffolding_model.py` docstrings, and `docs/COURSE_CREATION.md` (Quiz uses
  reviewed bank entries; the media types the Teacher upload accepts; threshold range) now
  match the code. Two design-intent mismatches are left as design history:
  `docs/teacher/BUILD_PLAN.md` and the "locked weeks" line in `docs/design/DESIGN.md`.

## Modes working together, first slice (2026-10-12)

Built, **(research)**, not yet measured with learners (see the CHANGELOG entry):

- [x] **Focused quiz review.** "Review with the tutor" teaches only the objectives the quiz got
  wrong.
- [x] **Mastered means skipped.** An ordinary tutor start teaches only objectives below their
  threshold; a fully mastered week starts already complete and asks "Do you want a refresher,
  or is it safe to move on?" instead of restarting at objective 1.

Still to do from the same design:

- [ ] **Refresher as a check.** For a mastered objective not practised for N days, one quiz
  item ("Quick check, or safe to skip?"). Needs a decision on N and on mastery decay; the
  simulator has no forgetting, so it cannot test this yet.
- [ ] **Learner record for memory.** Replace the unread long-term text summaries with a small
  structured per-objective record (last practised, times mastered, error types, help shown).
- [ ] **Quiz composition.** Whether a quiz should skip mastered objectives or interleave a few.
- [x] **Start panel** (2026-10-13). The Flutter tutor start panel shows, per learning
  objective, "Mastered" with a check, or "2 of 4 mastered", and the header says how many are
  already mastered and that LEA will skip them. A fully mastered week says there is no need to
  repeat the tutorial and points to the quiz.
- [ ] **Chat to Tutor nudge** when a student keeps asking about one objective.

## Registered tools and the learner profile (decisions 2026-11-03)

Checked by calling each tool's handler directly:

- **Web search** (DuckDuckGo): works. Kept. Not yet used in Chat.
- **Academic calendar**: kept, but it holds one demo institution with 2025 dates only, so today it reports "Term ended".
- **UK weather**: deleted (2026-11-03). The module it imported never existed, so it was never registered.
  `tests/test_tool_registry.py` now checks the exact set of registered tools.

Decisions made:

- **Chat always uses course retrieval first.** Chat already does. Any web search added later runs only when
  retrieval finds little, is labelled as not from the course materials, is off by default and per course, and
  is never used in Quiz or Tutor.
- **Learner profile: Option C.** The event log is the source of truth; a profile is rebuilt from it by a worker
  and cached in Redis, so a wrong profile can always be rebuilt.
- **Mastery of every objective and learning objective is logged** (built 2026-11-03): `mastery_change` on each
  graded answer and `mastery_milestone` when something becomes mastered or is lost, so mastered items are not
  repeated and the record survives a Redis loss.

A course can be built through the Teacher API by a test teacher account from linked course materials kept
outside git, then previewed as a student. Chat and Tutor both worked on such a course. Open: reviewing the
generated objective names in the Teacher area (unreviewed names are noted on the published version), and
whether a course built while the API is running is searchable without a restart (restart the API after a
build to be safe).

Further decisions (2026-11-03):

- **Profile visibility:** not shown to students; admin only. **Research use** needs a click-through consent
  statement, set up when a study is planned (consent today is a host command, `manage_account.py consent`).
- **Refreshers only trigger a check; mastery does not decay.** Recommended starting schedule (unvalidated, kept as
  configuration and tuned from the logged outcomes): re-check a mastered objective 14 days after it was last
  confirmed, then 28, then 56 after each pass; 7 days if it was mastered with a thin margin (within 0.05 of its
  threshold) or in few attempts; and offer a whole-week check after a gap of more than 30 days. A miss hands that
  objective to the tutor. The simulator has no forgetting, so this cannot be tested there yet.
- **Calendar for self-paced courses** (for example AIML101): the learner's own start date is week 1, so the
  calendar is per learner (optionally a target pace set by the module leader); the university term calendar
  applies only to modules run to a university term.

Still to do (designs, not built):

- [ ] **Course calendar.** A per-course calendar entered by the module leader (term, week-1 date, teaching weeks,
  assessments with release and due dates), on top of a university calendar file, replacing the hard-coded 2025
  dates. Assessment deadlines are not public; they come from each module's handbook.
- [ ] **Web search in Chat** as above, behind a per-course switch.
- [ ] **Learner profile worker and student-facing "what LEA knows about you" view.** Send reply timing first and
  make load baselines per course (they are per username today).

## Known limits

- **Tutor-reply grading kappa is about 0.6** against the simulator's intended
  correct/incorrect judgment -- real, but well short of good agreement. Treat a single
  tutor-reply grade as informative, not authoritative, especially near a mastery threshold.
- **The tutor contradicts its own lesson passage in about 5.5% of messages** (the smoke-run
  figure above). No grounding check exists yet to catch this at generation or grading time
  -- see the grounding fix open item below.
- **A meaningful share of tutor replies are never graded** -- about 28% in the smoke run,
  reduced by broad scope for the "related concept" portion of that but not the
  "another GO this week" portion (`credit_other_go`, below) or genuinely off-topic replies,
  which correctly stay ungraded either way.
- **The motivation classifier is weak.** In simulation, 89-91% of turns were classified
  `motivation_drop`, driven mainly by a noisy `performance_score < 0.5` rule against a grader
  that itself marks roughly half of right answers wrong; this is why support_off is the
  default (see `LEA_MOTIVATION_SUPPORT`'s docstring in `scaffolding_model.py`) and why
  `LEA_MOTIVATION_CLASSIFIER`'s `no_performance` alternative exists, though it too is
  unvalidated on real students.

## Open items (not built this round, by design)

- **`credit_other_go`**: crediting a question that's clearly about a *different* same-week
  GO to that GO instead of leaving the turn ungraded. Drafted, not built -- needs its own
  validation pass, not bundled into this round's broad-scope change.
- **The grounding fix**: a dedicated check that the tutor's own generated message doesn't
  contradict the lesson passage, independent of the ~5.5% contradiction rate above (which is
  currently only measured, not caught or corrected in the running app).
- **Motivation classifier**: the `no_performance` alternative is built and selectable
  (`LEA_MOTIVATION_CLASSIFIER=no_performance`) but not validated against real students.
- **Flutter timing capture**: the app doesn't yet record how long a student takes to reply,
  which is what's blocking `LEA_COGNITIVE_LOAD_MODEL=personal` and
  `LEA_SCAFFOLDING_MODEL=load_led` from being turned on by default.
- **A full baseline simulation** under the new tester configuration (one-question tutor,
  broad scope) hasn't been run -- this round's evidence is a smoke-run comparison sized to
  decide the temperature and default flips above, not a full pilot.
- **Per-GO code eligibility**: `allows_code` is course-wide (`data/course_profiles/*.json`);
  there's no way yet to allow code for GOs whose own lesson passage actually contains code
  while disallowing it elsewhere in the same course. AIML101 is `allows_code: false`
  entirely for now (2026-09-28 addendum, above) rather than build this. The KC model already
  carries per-GO fields (`skill_category`, `cognitive_level`) that drive whether a question
  *would* include code, so the natural place for this is an added per-GO field there, read
  alongside the course-level gate in `simple_quiz_system.py`'s `_generate_question`.
