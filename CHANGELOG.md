# Changelog

The backend is being refactored in phases ahead of a Flutter front end. Each phase
leaves a working Streamlit app. The code used for the published papers is in
[tep00018/LEA](https://github.com/tep00018/LEA), tag `v1.0-snsc`.

| Phase | Scope | Status |
|---|---|---|
| 0 | Stabilise the repo | Done |
| 1 | Fix the adaptive loop | Done |
| 2 | Extract a service layer (typed session models, sessions in Redis) | Done |
| 3 | HTTP API (FastAPI, token auth, streaming) | Done |
| 4 | Flutter app, web first | Done |
| 5 | Onboard private courses | Done |
| 6 | Open demo course (AIML101) and the Teacher module | In progress |

Changes marked **(research)** affect grading, mastery, adaptation or what students see,
and were approved by the researcher first.

## Simulation v2 (AIML101), in progress

Two fixes to linked folders found when re-indexing a course on 2026-11-03. A Build job's `profile` step rewrote the course
profile from scratch and silently dropped the linked folder, so later builds saw no files (`src/onboarding/pipeline.py`
now keeps the fields it does not own). And a linked file always became "Week00": the sync now reads the week and kind
a file name states, as in `Week02-Lab-Notes.md` (`infer_week_kind`, `src/onboarding/files.py`), uses them when the
week is within the course, and no longer doubles the prefix in the staged name. A name without a week still becomes
Week00. Tested in `tests/test_materials_source_api.py` and `tests/test_onboarding.py`; the profile test fails without
the fix.

Fixed: a published objective model containing curly quotes or accented letters could not be opened on Windows. The
model loader (and the mastery file backup) read their JSON with the platform's default encoding instead of UTF-8, so
`GET /courses/{code}/outline` returned 500 for the first course built from non-ASCII text (a course with non-ASCII text, found on
2026-11-03). Both now read and write UTF-8 (`src/core/kc_model_loader.py`, `src/core/mastery_tracker.py`);
`tests/test_kc_model_encoding.py` fails without the change.

Mastery is now written to the event log. Every graded answer writes a `mastery_change` event (the objective's level
before and after, threshold, and mastered or not, for the objective and its learning objective) and a
`mastery_milestone` event when an objective or learning objective becomes mastered or is lost
(`src/services/mastery_log.py`). This is the durable learner record that a rebuildable profile and the refresher
check will read; it changes no grading, mastery or adaptation. Tested in `tests/test_mastery_log.py`. The UK weather
tools were removed: their module never existed, so they were never registered (`src/mcp/tool_registry.py`;
`tests/test_tool_registry.py` now checks the exact set of registered tools).

Documentation and lint only, no behaviour change: `docs/ARCHITECTURE.md`, `docs/COURSE_CREATION.md`, `docs/API.md`,
the recorded-question wording here, and two `scaffolding_model.py` docstrings now match what the code does (see
`docs/STATUS.md`). Removed the one `flutter analyze` warning (an always-true null check in
`app/lib/tutor/tutor_controller.dart`); `flutter analyze` and `ruff check .` are both clean.

The Flutter tutor start panel now shows what the student has already mastered: a check and "Mastered" beside a
learning objective whose granular objectives are all mastered, "2 of 4 mastered" for part of one, and a header that
says how many are mastered and that LEA will skip them. It reads the same `GET /courses/{code}/mastery` data as the
Progress screen; no API change. Lint is clean again: the 30 ruff errors (unused imports and variables, and pytest
fixture re-imports in `tests/test_materials_source_api.py`, now a per-file ignore) were cleared; no behaviour change.

**(research)** The tutor no longer repeats what a learner has mastered (`src/services/tutor.py`,
`select_objectives`). A review started from a finished quiz teaches only the objectives that quiz got wrong (before,
it knew what was missed but still walked the whole week). An ordinary start teaches only the objectives below their
mastery threshold, in week order (before, it began at the first unmastered one and then taught every later one,
mastered or not). If every objective in the week is already mastered, the session starts already complete with a
plain message ("Do you want a refresher, or is it safe to move on?", pointing to the quiz for a refresher) and the
learner moves on as finishing the tutorial would have; before, it restarted at objective 1. The `tutor_start` event
records `selection` (`quiz_missed`, `unmastered` or `all_mastered`), `week_objectives` and `skipped_objectives`.
Tested in `tests/test_services.py`. Not yet measured with simulated or real learners; the simulator has no
forgetting, so the refresher question itself (design item 3) is not built.

Fixed: the API's cross-origin allow-list permitted only GET, POST and DELETE, so a browser on another
origin (the web app on port 5100, the API on 8100) was refused at the preflight for the PUT and PATCH calls the
Teacher and admin screens make (weekly plan, draft objectives, enrolment, owners, audit decisions, account
edits). PUT and PATCH are now allowed (`src/api/app.py`); origins are unchanged. Found by reading the code while
writing the white paper; the failing preflight is reproduced by `test_cors_preflight_allows_every_method_the_client_uses`.

**(research; on by default since 2026-09-27, off with `LEA_TUTOR_RECORDED_QUESTION=off`)** The tutor ends each reply with
exactly one checkable question about the current objective, states only facts the course content supports (no
invented dates, names or numbers), and keeps replies to about 200 words (`LEA_TUTOR_RECORDED_QUESTION`; `SimpleTutorSystem._extract_recorded_question`).
When the student's reply arrives, a short, non-streamed extraction call -- run at grading time, not when the
tutor's message was generated, so it adds no latency to the tutor's turn and nothing is spent if the student never
replies -- records the one required question from the tutor's last message and confirms it is about the current
GO. Grading then judges the reply against that recorded question and the GO's reference, and a turn with no valid
recorded question is left ungraded. Built after an offline replay measured 24% of tutor messages drifting off the
current objective across four pilots (`simulation/runs/grader_replay/go_drift.json`); not yet measured live.

**(research)** The tutor's and quiz's free-text grader (`src/core/grading.py`) now judges an answer only against
the question actually asked; accepts a brief answer that answers the actual question, without requiring every
part of a multi-part message; accepts fill-in synonyms and paraphrases; marks an answer incorrect if it
contradicts the reference or lesson passage; and still credits an otherwise-correct answer that also makes an
unrelated wrong side remark (the remark is corrected in the feedback instead). A reply is left ungraded (never
right, wrong, or counted toward mastery) when the tutor's message asked nothing checkable (`with_confidence`, now
`True` by default). Chosen as "V5" from an offline replay of candidate graders against 1,108 saved answers from
pilot-1 through pilot-4, scored against the simulator's known intent (`simulation/grader_replay.py`; no simulation
or Claude calls). Weighted-by-type kappa against intent went current 0.472 -> V3 (question-scoped, checkable gate
only) 0.491 -> V5 0.567 tutor / 0.661 fill-in / 0.381 open-ended, then a further researcher-adjudicated fix (the aside
rule above, found from a 25-item blind researcher review of V3's disagreements with the simulator's own recorded
intent) raised V5 to 0.594 tutor / 0.661 fill-in / 0.432 open-ended (all vs. original intent; higher again, 0.622 /
0.661 / 0.479, when scored against the researcher's adjudicated intent for those 25 items -- about a quarter of them
turned out to be simulator mislabels, not grader errors). No candidate reaches M4's own kappa target of 0.70; this
is an incremental improvement, not a fix. Pass `with_confidence=False` for the original, ungated grader.

**(research)** The motivation state no longer moves the scaffolding support level; it is still classified, logged
and used for feedback tone (`LEA_MOTIVATION_SUPPORT`, now `off` by default, was `on`). Simulation Amendment A3
(`simulation/PREREGISTRATION.md`) found LEA classified about 90% of tutor turns as a "motivation drop" -- driven
mainly by recent accuracy against a noisy grader -- and that this shift accounted for most "very high" support
decisions, masking every earlier comparison of the ZPD and cognitive-load rules. Turning it off cut support
mismatch against the simulator's hidden true load by 15 to 17 percentage points (Holm-corrected paired Wilcoxon,
p <= 0.01, 12 simulated learners). Set `LEA_MOTIVATION_SUPPORT=on` to restore the previous behaviour.

**(research, off by default)** A personalised cognitive-load equation beside the existing one
(`src/core/cognitive_load.py`, selected by `LEA_COGNITIVE_LOAD_MODEL=personal`; the default is unchanged). It uses
optional client timing (`timing` on tutor replies and quiz answers: response and typing time, hint requests, a
relative effort rating), each student's own baselines, and time-on-task fatigue. Both equations are logged every
turn with timing. Two alternative ZPD and support rules sit behind `LEA_SCAFFOLDING_MODEL` (`zpd_shrunk`, `load_led`;
`current` is the default and unchanged; `load_led` also has the tutor's grader report whether a question was checkable and how
confident it is, used only to weight evidence for ZPD and fading, never the grade or mastery). The simulation's students now have a hidden personal load that produces those signals
(`simulation/signals.py`), and `python -m simulation compare-arms` compares the two equations on the same learners.

A new simulation study in `simulation/` (plan: `docs/simulation/PLAN.md`; guide:
`simulation/README.md`). No change to LEA: nothing in `src/` was modified; the simulator
calls the services as the API does and observes from inside its own process.

- S0: run isolation (per-run AIML101 copy, fakeredis only, writes under `data/` refused),
  run manifest, and a Claude client that calls `claude -p` through a Claude subscription
  (Anthropic variables stripped, `apiKeySource` must be `none`, no API-key fallback) with
  usage guards (overage stop, limit and utilization pauses, rolling budgets, call cap, run
  hours, usage-credits confirmation).
- S1: learners with hidden Bayesian Knowledge Tracing state and engagement, six profiles.
- S2: the AIML101 question bank (63 objectives), built with Claude and committed.
- S3: Chat, Tutor and Quiz drivers with full capture; checkpoints and resume.
- S4: batched, blind, schema-validated judges with versioned rubrics; reliability samples
  and the blind labelling sheet.
- S5: every metric with cluster-bootstrap CIs, reliability gating, the report, calibration
  and sizing (`plan`). New optional extra `sim` (statsmodels, matplotlib).
- S6 (partial): a first pilot (4 of 6 learner-weeks, 400 Haiku calls) found the student's hidden
  reasoning was 90% of the Claude cost; it is now switched off for the student. First allowance
  calibration; draft pre-registration (`simulation/PREREGISTRATION.md`) and pilot report
  (`docs/simulation/PILOT_REPORT.md`) awaiting the researcher. No change to LEA.

**(research)** Fixed a course-blind quiz-question failure mode found in hand testing: AIML101's Week 1 quiz built a
"Weak AI vs Strong AI" question around two toy Python functions, then keyed the expected answer to calling the
second one "Strong AI" -- a false premise, since neither function demonstrates general intelligence or
consciousness, and a student who correctly said so was marked wrong. `allows_code` is now `false` for AIML101
(`data/course_profiles/AIML101.json`) until a finer, per-GO "does the lesson passage itself contain code" rule
exists (open item, see `docs/STATUS.md`) -- a scan of every pilot and smoke run's saved quiz items
(`simulation/runs/*/events.jsonl`, no model calls) found 423 of 4,330 quiz turns contained code, all of them this
one objective (`GO_01_01_004`, "Compare Weak And Strong Ai"), none elsewhere. The quiz generation prompt
(`src/quiz/simple_quiz_system.py`) now also tells the model never to build a question (or its expected answer) on
a premise the course content doesn't support, and never to use a toy code example to stand in for something code
can't actually show.

**(research)** The V5 grader (`src/core/grading.py`) now marks an answer correct, and says so in the feedback,
when the student correctly points out that the question's own premise or example is flawed or mischaracterized --
previously this read as a non-answer to the question actually asked. Unit-tested only
(`tests/test_grading.py::test_a_correctly_identified_false_premise_is_graded_correct`); not re-run through the
offline replay.

## Unreleased

### Enrolling in another course after registration
- An existing account can add or drop courses without creating a new account: self-service
  (`POST`/`DELETE /me/courses`, "Add a course…" and a per-course "×" to leave in the course
  picker, the latter behind a confirmation dialog) or admin-driven for any account
  (`PUT`/`DELETE /admin/users/{username}/courses/{code}`, from the Edit dialog in Users and
  owners). Previously `courses` at registration was the only way to set an account's
  enrollment, ever. Un-enrolling doesn't delete progress in that course -- re-adding it
  later resumes where it left off. Both kinds of change go to the event log. No change to
  grading, mastery or adaptation.

### Reference question banks in Quiz mode
- **(research)** A multiple-choice or true/false question backed by a reviewed reference-
  question-bank entry (`tagging.reviewed: true`, matched by exact `go_id` and question type
  in `data/course_sources/<CODE>/question_bank.json`) is now given to the student verbatim
  instead of generating one with a model -- mixed in alongside LLM generation, not a
  replacement for it: a GO with no reviewed, type-matching bank entry generates exactly as
  before. Grading is unaffected (`src/core/grading.py`'s `grade_multiple_choice`/
  `grade_true_false` already don't care how a question was produced). An unreviewed entry
  (the default for an auto-tagged bank) is never used this way; it still only counts toward
  the content audit's question checks. `src/quiz/simple_quiz_system.py::_bank_question`.

### Linked materials sources for the Teacher area
- A course can link a read-only folder of materials (`LEA_COURSE_MATERIALS_ROOT`, one
  subfolder per course code) instead of, or alongside, uploading files one at a time. The
  folder must resolve inside the root (no `..`, no absolute path, no symlink leading
  outside it); a `_`-prefixed folder (e.g. `_teacher`) or a hidden file/folder is never
  even offered as a candidate. New endpoints under `/teach/courses/{code}/materials-source`
  (link, unlink, a read-only sync preview) and `/teach/materials-folders` (see
  `docs/API.md`). `src/onboarding/materials_source.py`'s `MaterialsSource` interface (list
  files, read a file, fingerprint a file) has one implementation today (a local folder), so
  a connector to an existing system (Canvas, Moodle, SharePoint, Google Drive) can be added
  later without changing the Teacher screens.
- A Build job reconciles a linked folder's current files into the course's normal uploads
  before pricing, so the existing upload pipeline (pricing, confirmation, embedding) does
  the actual ingesting with no changes of its own: unchanged files are skipped, and an
  upload whose linked file was removed from the folder is removed too. Uploads keep working
  alongside a linked source; a linked upload carries `linked_relpath` and shows a "Linked"
  badge in the Teacher app.
- No change for students -- this is Teacher-only plumbing for supplying course content.

### YouTube help: cached, paced, and chosen by instructors
- **(research)** Video help for a stuck student now appears **once per stuck streak**, when the
  streak reaches three wrong answers in a row. Before, it was added to every wrong reply from
  the third on (and searched YouTube each time). A correct answer or a new objective resets
  the streak.
- **(research)** Automatic search is cached for a week per objective, so students see the
  same videos for an objective for up to a week. Before, every reply searched Google again
  (about 101 of the 10,000 daily quota units each). After a quota error, no search is sent
  until the quota resets at midnight Pacific; a failed query isn't retried for ten minutes.
- **(research)** Instructor-curated videos: an instructor can attach up to five YouTube videos,
  with notes, to any objective. The tutor shows them (the first three, in the instructor's
  order) instead of searching. New endpoints under `/teach/courses/{code}/videos` (see
  `docs/API.md`); lists live in `data/course_videos/<CODE>.json`.
- Teacher screens **Videos** (overview: your videos per objective, what a stuck student gets,
  and **Help shown**, the real students shown video help in the last 30 days, withheld below
  5 as in Analytics; a banner when automatic search is paused) and the per-objective editor
  (ordered list, add by link with a note, remove with *Add it again*, and a preview of what a
  stuck student sees). Read-only on a phone. Section 5 of the teacher guide.
- Tutor `answer` events now record `youtube_source` (curated, search:api, search:cache,
  search:search-link or fallback), for studies of what help students were given.
- The test suite blanks `YOUTUBE_API_KEY` instead of deleting it (a later `load_dotenv()`
  brought the real key back, so tests could search YouTube for real).

### Fix: API keys no longer reach logs or error results (no change for students)
- A failed YouTube search returned, and the tutor then logged, Google's error text, which is
  the full request URL including `key=...`. `src/core/redact.py` removes API keys, tokens
  and URL passwords from text (`redact()`), the YouTube tool no longer returns the raw error,
  and `build_services()` installs a log-record filter so a secret that reaches a log call by
  any other route is cleaned too (messages, arguments and tracebacks). Tests use made-up
  keys and show the old behaviour leaked.
- If a key was ever visible in a log or a terminal, rotate it in Google Cloud.

## Phase 6: Open course and Teacher module

Plan: `docs/teacher/BUILD_PLAN.md`; evidence: `docs/teacher/RESEARCH.md`.

### B1. Durable event log (no behaviour change)
- `data/lea_events.db` (SQLite, WAL, gitignored): one append-only `events` table with the
  course, KC version (a hash of the KC model file), pseudonymous learner, session kind
  (`real`, `test`, `simulated`), mode, event type, GO/LO/week, correct, score, question
  type and a JSON payload. The Redis evidence list still keeps only the last 50 answers;
  this log keeps everything.
- Written by the services: quiz start/answer/end (with the question, options and expected
  answer), tutor start/reply/end (diagnostic, consecutive incorrect, YouTube help,
  advancement), chat questions, each learner assessment, and the cognitive-load,
  scaffolding and motivation decisions already written to the CSV logs.
- Learners are an HMAC of their username with `LEA_EVENT_SALT`; usernames inside quiz and
  tutor session IDs are replaced too. Chat and answer text is stored with the student's own
  username and name removed (not full anonymisation).
- Accounts have a `session_kind` (default `real`) and `research_consent` (unset until the
  registration question is added). Test accounts are tagged `test` and left out of the CSV
  research logs at write time. `scripts/manage_account.py set-kind` and `consent`, with an
  audit trail of staff actions (real actor names) in the log.
- `scripts/export_events.py`: research export of consented real learners (or simulated
  ones); test sessions and staff actions are never exported.
- Recording never raises: a failed write is logged and counted, and the student's turn
  carries on. Without `LEA_EVENT_SALT` the log is off.

### A1–A3. AIML101, the open course
- **(research)** Students now see **AIML101, Introduction to AI and Machine Learning (open
  course)** instead of DEMO101, and it is suggested at registration (Flutter and
  Streamlit). Six weeks from Microsoft's MIT-licensed *AI for Beginners* (392d0df) and
  *ML for Beginners* (de2d4e1): 32 lesson files (English text, no images), 17 learning
  objectives written by the researcher, 63 granular objectives drafted with GPT-4o and
  reviewed (five duplicates removed, mastery thresholds capped at 0.85), Python code
  questions allowed. Licences and `ATTRIBUTION.md` in `data/course_sources/AIML101/`.
- A 67-question reference question bank from the curricula's quizzes, tagged to
  granular objectives (unreviewed suggestions). Quiz mode doesn't use it.
- Onboarding: Markdown ingestion; `kc_model_generator.py --model`; `stage_aiml101.py`,
  `finalize_aiml101_kc.py` and `build_aiml101_question_bank.py` rebuild the course from
  the pinned commits.
- DEMO101 moved to `tests/fixtures/data/`; tests run against it (plus AIML101) instead of
  a copy of all of `data/`, so they no longer see other courses. A smoke test covers
  AIML101's structure, profile, per-week content, licences and question bank.

### B2. Roles, course ownership and admin endpoints (no change for students)
- Accounts have a `role` (`student` by default, `teacher`, `admin`), returned in `/me`
  (a new field; the Flutter model reads it, nothing is shown yet).
- `/admin/users` (list; create a teacher or admin; change a role; deactivate, which signs
  the account out everywhere) and `/admin/courses/{code}/owners`. The last active admin
  can't be demoted or deactivated, and nobody can deactivate themselves.
- `/teach/courses` and `/teach/courses/{code}`: the first Teacher-area endpoints. Course
  ownership is `course:{code}:owners`; admins reach every course.
- Every `/admin` route is 403 for non-admins and every `/teach` route for students
  (checked before the request body is read); a teacher gets the same 403 for another
  teacher's course and for a course that doesn't exist. New error codes `NotPermitted`
  (403) and `NotFound` (404).
- `manage_account.py make-admin | make-teacher | make-student`. Staff actions go to the
  event log's audit trail.

### B3. Course onboarding as background jobs (no change for students)
- `POST /teach/courses` sets up a course (the creating teacher owns it); it stays hidden
  from students until a KC model is published. `PUT .../objectives` stores the weekly
  learning objectives the KC model is drafted from.
- Uploads: PDF, DOCX, PPTX, XLSX, MD, TXT, IPYNB, MP3, MP4, WAV; checked by extension and
  content; 50 MB per file, 1 GB per course; stored in `data/course_uploads/` (gitignored).
- Jobs run in the API process (a worker thread; Streamlit never runs them): convert ->
  transcribe -> chunk and embed -> draft KC model (GPT-4o) -> course profile -> verify
  retrieval. Each is priced first and runs only when the teacher confirms; one per
  course; cancellable between files; progress, log and result in Redis; interrupted jobs
  are marked failed on restart. Re-runs skip unchanged files and remove deleted uploads
  from the index.
- The drafted KC model goes to `data/kc_models/<CODE>/drafts/` (gitignored) with each
  objective's best-matching excerpt; it is never published by a job. Objective titles are
  the teacher's own text (the generator's names can be misaligned, as seen with AIML101).
- Onboarding code: `rag_library_creation.py` takes a data folder and transcribes MP3/WAV;
  new dependency `python-multipart`.

### B4. KC versions, review and publishing
- Published versions (`kc_models/<CODE>/versions/v<n>.json`) and one draft per course;
  `kc_model_<CODE>.json` stays the live copy LEA reads. A course from before versioning
  is version 0 until its first publish records it as v1.
- The draft is a table of granular objectives (week, learning objective, name,
  description, Bloom level, threshold, keywords, prerequisites as GO IDs). Only LEA assigns
  IDs; IDs never change or come back once retired; splits, merges and retirements go into
  the model's lineage and an ID ledger. The prompts' `prerequisite_concepts` (names) are
  rebuilt from the IDs, so the tutor and quiz see the same kind of text as before.
- Validation (IDs, duplicates, thresholds 0.5-0.95, Bloom levels, prerequisites and
  cycles, every week covered), XLSX export with locked ID columns and a read-me, and import
  that changes nothing unless the whole sheet is valid.
- Diff against the live version with the number of students affected.
- **(research)** Publishing carries mastery along the lineage: split parts get the old
  objective's mastery, a merge the mean of the student's mastery on its sources; retired
  objectives keep their mastery but no longer count (approved by the researcher, 2026-09-25).
  Mastery values change only for students with mastery on a split or merged objective;
  the evidence history is untouched.
- Every process reloads a KC model whose file changed, so a publish reaches Streamlit
  without a restart.
- Research data: the event log records each draft save (added, changed, removed) and, on
  publish, the counts, number of saves, review time and students affected.

### B7. Try as a student (no change for students)
- A sandbox student account per teacher (`<teacher>.preview`, random password, tagged
  `test` from the start) with its own token; reset forgets its activity in a course.
- Teacher-only explanations of preview turns (objective, mastery before and after,
  grading, learner model, scaffolding, retrieved content) at
  `/teach/courses/{code}/preview/explain`, recorded only for sandbox accounts. Instead of
  a `debug` field on student responses (the plan's wording), a separate endpoint, so
  student responses are unchanged and can never carry it.
- Retrieval now also reports its sources (an extra field) so the explanation can show
  them; prompts are unchanged.
- **Flutter Teacher area** (`/teach`, teachers and admins only; wide screens first, read-only
  on phones), following `docs/teacher/design/`: a "Teaching" link in the student rail;
  Courses (state, owners, counts, build progress, New course); Setup and materials
  (uploads, weekly objectives, the Build card that prices a build and runs it only when
  started, with progress, log and cancel); Objectives (the draft by week and learning
  objective with IDs, Bloom, threshold and content match; row details to edit; add,
  split, merge, remove; checks; Excel export and import); Review and publish (every
  change, students affected, the research note); Try as a student (the student screens as
  the sandbox with a banner that can't be dismissed, and the explain panel on wide
  screens). No change for students.

### B5. Content audit, and the admin screens (no change for students)
- `POST /teach/courses/{code}/audit/runs`: findings about the live version, each with its
  evidence and evidence tier (see `docs/API.md`): accessibility of the files, question
  writing in the reference bank, Bloom balance, prerequisite order, coverage, redundancy,
  alignment with the reference questions, readability and slide density. Ranked and
  capped per check; only coverage and redundancy use OpenAI (embeddings).
- Accept, dismiss with a note, or reopen; decisions are kept by stable finding keys across
  runs, and each run says what is new and what was resolved. Runs are files in
  `data/audits` (gitignored); runs and decisions go to the event log (precision data).
- App: the Content audit screen (run with its cost, filter by check, accept/dismiss/reopen,
  new and resolved findings) and, for admins, Users and owners (every account with role
  and status; search and filters; edit role, active and test account; course owners;
  new teacher accounts). `PATCH /admin/users` also takes `session_kind`.

### B6. Student analytics (no change for students)
- `GET /teach/courses/{code}/analytics` and `.../objectives/{go_id}`: mastery bands, first-
  attempt accuracy, attempts to master, learning curves with a verdict, common wrong
  answers, tutor struggle and a "needs attention" heuristic with its driver and a drafted
  suggestion. Computed from the event log only; real students by default, simulated on
  request, never mixed; test accounts, preview sandboxes and staff never counted. Any
  figure from fewer than 5 students is withheld.
- Aggregated learning-curve CSV; chat topics (GPT-4o mini, two passes with agreement,
  topics from 5+ students only, run on request with its cost); an explainer draft per
  objective. Views are logged as staff actions.
- `scripts/seed_simulated.py`: simulated students (tagged `simulated`) to try the screens.
- App: Analytics (bands summary, objectives most in need first with the factor behind each,
  week and date-range filters, Real/Simulated students, usage last, curves CSV) and the
  objective detail (learning curve against the course's typical curve with a one-line
  reading, common wrong answers, tutor struggle, chat topics run on request with cost and
  agreement, LEA's suggested action with Edit note / Dismiss, Draft an explainer).

### B9. Teacher guide, study instrumentation and the end-to-end run (no change for students)
- `docs/teacher/GUIDE.md`, for teachers: the Teacher area from first login to analytics.
  `docs/SETUP.md` covers the first admin, backing up the event log and what else to back up,
  and seeding simulated students.
- More detail in the teacher actions logged for a later study: the objectives each draft
  save and each publish touched (and which fields), what an accepted or dismissed audit
  finding points at, and which objectives analytics flagged when viewed. Review time and
  draft saves were already logged.
- `scripts/export_events.py --teachers`: teacher and admin actions only, with every
  teacher pseudonymised, including usernames inside payloads (such as the preview
  sandbox's name). LEA doesn't record teacher consent: get it separately for a study.
- An end-to-end test of the whole journey (an admin creates a teacher, who creates a
  course, uploads, runs the job, reviews and publishes, audits, previews and sees simulated
  analytics), checking that the sandbox never reaches real analytics or exports.
- KC drafts in progress (`versions/draft.json`) are no longer picked up by git.
- `openpyxl`, `python-pptx` and `pdfminer.six` are now core dependencies (the Teacher area's spreadsheet and
  file audit need them), not only part of the `ingest` extra.

## Phase 5: Private courses

- A first private course onboarded (private course data is never committed).
- Learning objectives show a `short_title` in the outline and mastery views.
- Re-indexing a changed file replaces its chunks; Whisper loads only for videos.
- `data_foundation/clean_transcripts.py`: GPT-4o clean-up of lecture transcripts.
- **(research)** "Review with the tutor" starts a tutor session that knows the quiz just taken (the
  tutor's wording only; grading, mastery and objective order unchanged).

## Phase 4: Flutter app

The Flutter client in `app/` (web first; the code has no web-only screens, so Android and
iOS can follow). Streamlit keeps working alongside it. No changes to adaptation, grading or
mastery.

### The app
- Chalkboard theme (colour tokens for light and dark, following the system), Bricolage
  Grotesque, Lexend and JetBrains Mono bundled (OFL), so nothing is fetched at runtime.
- Responsive shell: a rail with course and week pickers and Chat/Tutor/Quiz tabs at 720 px
  and wider; a top bar, course sheet and bottom navigation below.
- Login and account creation; the token is kept in secure storage and checked on start;
  a 401 anywhere returns to login with "Please log in again."
- Chat and Tutor with replies streamed over SSE on POST (`fetch_client` on web, the
  default HTTP client elsewhere) and a tested SSE parser. Tutor shows the objective, the
  step indicator by learning objective, the support pill, and counted/warm-up tags.
- Quiz: all four question types, feedback with your answer and the right one, results
  with every question's objective, week advancement.
- Progress: week cards and each objective's mastery against its threshold.
- Loading skeletons, API error messages with retry, an offline banner that clears when the
  server is back, keyboard focus rings, screen-reader labels, reduced motion and text up
  to 200%, checked by tests on every screen (contrast on the tutor session screen by its
  colour pairs, as Flutter's pixel check mis-measures one of its links on Linux).
- Only weeks up to the current one can be opened; later weeks show when they unlock.
- 212 widget and unit tests against a fake API; a render tool for comparing screens with
  the design.
- LEA's local ports: API 8100, Streamlit 8600 (`.streamlit/config.toml`), web 5100/5101.

### Design and handoff

### Design and handoff
- Approved design: Chalkboard palette, Bricolage Grotesque and Lexend. Spec, screenshots
  of every screen (light/dark, desktop/phone) and the interactive mockup in `docs/design/`.
- `docs/design/BUILD_PLAN.md` for building the app.

### API additions for the app
- `GET /courses/{code}/mastery?week=N`: each objective's mastery against its own
  threshold, grouped by learning objective (the same rule as week completion).
- Quiz feedback includes `your_answer` and, for multiple choice and true/false,
  `correct_answer`, only once the question has been answered.
- `TutorView.scaffolding_strategy`: how the tutor is scaffolding (the session already
  stored it), for the tutor header's support pill.
- Quiz feedback and results include `go_id`, the objective each question tested.
- `.gitignore`: Python build rules are anchored to the repository root, so the Flutter
  app's `lib/` folder isn't ignored.

## Phase 3: HTTP API

The API the Flutter app will use, plus conversation memory in Chat. Streamlit keeps
working and can run alongside the API. Research-relevant changes are marked **(research)**.

### API
- FastAPI app in `src/api`, run with `uvicorn src.api.main:app`. Endpoints for accounts,
  courses, progress, chat, quiz and tutor; see `docs/API.md`. The OpenAPI spec is committed
  at `docs/api/openapi.json`, and a test fails if it falls out of date.
- Chat and tutor replies can be streamed as server-sent events.
- Clients never receive quiz answers, question plans, grader details or learner-state
  snapshots.
- Errors are JSON `{detail, code}` with conventional status codes.
- CORS allows any `localhost` port by default (the Flutter dev server); `LEA_CORS_ORIGINS`
  adds others.

### Security
- Login tokens are validated on the server for every request. Only a SHA-256 hash of
  each token is stored. A token expires after 12 hours unused and 7 days at most, logout
  ends it immediately, and deactivating an account stops its tokens. (Before, session ids
  were issued but never checked, and the backend trusted any username it was given.)
- Identity comes only from the token; course endpoints check enrolment.
- Passwords are hashed with argon2id (OWASP baseline settings). Existing PBKDF2 accounts
  keep working and are re-hashed at their next login. Unknown usernames take as long to
  reject as wrong passwords.
- Rate limits (see `docs/API.md`): login attempts per username and address, counted
  before the password is checked so parallel guesses can't exceed them; a higher
  per-username ceiling, so one device can't lock a student out everywhere; generous
  per-address limits (a class may share one address); model-backed actions per user and
  per address.
- Registering a username is atomic (two simultaneous sign-ups can't overwrite each other).
- Questions, answers and replies are limited to 4,000 characters; passwords to 128.
- `scripts/manage_account.py`: reset a password, deactivate or reactivate an account, or
  end its sessions.

### Chat conversation memory
- **(research)** Chat now sends the earlier messages of the current sitting (up to 10,
  since the last 30-minute gap) to the model, so follow-up questions make sense. Before,
  each question was answered on its own.
- **(research)** A short follow-up that refers back (12 words or fewer, containing a word
  such as "it", "that", "example", "why") is searched in the course material together
  with the question before it: "can you give an example?" is searched with "what is
  supervised learning?", while "what is a Q-table?" is searched on its own.

### Other
- Streamlit logs out properly (the login token is revoked).
- Tests: 149, including every endpoint, cross-user isolation, token expiry and
  revocation, password upgrade, rate limits under parallel requests, streaming and chat
  memory.

### Still open
- Tutor replies are generated from the current reply and objective, without the earlier
  turns of the session (as in the paper version).
- Password reset needs the admin script (no email flow).
- The academic-calendar tool still has 2025 term dates; no flow uses it yet.

## Phase 2: Service layer

The Streamlit app looks and behaves the same. Underneath, every operation now goes
through services that the HTTP API (Phase 3) and the Flutter app (Phase 4) will reuse.
Research-relevant changes are marked **(research)**.

### Services
- `src/services`: `accounts`, `courses`, `progress`, `learning` (the adaptive loop shared
  by Quiz and Tutor), `chat`, `quiz` and `tutor`, built once by `build_services()`.
  See `docs/ARCHITECTURE.md`.
- Quiz, tutor and chat sessions are typed (Pydantic) and stored in Redis with a TTL
  (quiz and tutor: 1 day; chat: 14 days). A page refresh, a second tab or restarting LEA
  resumes a quiz or tutor session where it was.
- The quiz and tutor engines keep no per-session state in memory; the question-variety
  trackers travel with the quiz.
- `streamlit_app.py` is now UI only (3,114 → about 650 lines); avatars moved to
  `src/ui/avatars.py`.

### Synchronous code
- The backend is plain synchronous Python. The `async` functions never awaited anything
  non-blocking (OpenAI, Redis, ChromaDB and the reranker are blocking libraries), so they
  held up other students anyway. The API will run each request on its own thread.
  `run_coroutine_sync`, the event-loop juggling in Streamlit and `pytest-asyncio` are gone.
- The OpenAI client has a 60-second timeout (the SDK default is 10 minutes); YouTube
  calls have a 10-second timeout.

### Concurrent use
- Short Redis locks guard every read-modify-write of shared learner state: mastery,
  motivation history (the orchestrator's assessment) and week progress. Before, two tabs
  answering at once could overwrite each other's mastery update.
- Each stored session has a lock, renewed while slow model calls run. A double click or
  a second tab gets "Still working on your last request" instead of the answer being
  graded and recorded twice.
- The reranker and the YouTube client, which aren't thread-safe, are used one call at
  a time.

### Memory consolidation
- A session is queued for consolidation once, not once per memory after the fifth.
- Only the memories that were summarised are removed afterwards. Memories that arrived
  during summarisation used to be deleted unsummarised.
- A per-session lock stops two workers (Streamlit and the API, later) from summarising
  the same memories; unreadable entries are skipped.

### Behaviour changes
- **(research)** Research logs now write plain values: `mode` is `quiz`/`tutor` (was
  `AppMode.QUIZ`/`AppMode.TUTOR` in the motivation metrics file, and `unknown` for quiz
  answers in the decision logs) and `persistence_level` is e.g. `maintains_persistence`
  (was `PersistenceLevel.MAINTAINS_PERSISTENCE`). Column layouts are unchanged. A month
  that spans the upgrade has both spellings in `motivation_metrics_YYYYMM.csv`.
- **(research)** Q for Chat counts the questions in the current sitting, which ends
  after 30 minutes without a message. Before, it counted per browser session and reset
  on refresh.
- **(research)** Tutor: finishing or ending a session moves the learner to the next week
  if a graded reply completed the current one. Before, a completed week was only
  applied the next time the learner started a new quiz.
- A quiz or tutor session left unfinished on one week still counts towards moving on
  when the learner starts one on another week.
- Chat history is kept per learner and course, and survives logging out. A failed chat
  reply says so ("Sorry, I couldn't answer that just now") instead of a canned
  answer, and the unanswered question isn't counted.
- Changing course opens the learner's current week in that course (it opened week 1).
- Changing week no longer abandons a quiz: returning to its week resumes it.
- Removed the tone prefixes the Streamlit app added to tutor replies; they never
  applied, because the performance score they checked was never passed.
- The decision and motivation CSV writers moved to `src/core/research_logs.py`, with
  thread-safe writes.

### Tests
- 119 tests. New: service flows for quiz, tutor and chat; resuming after a restart;
  double submit; parallel mastery updates (these two fail without the locks); week
  advancement; lock renewal; research-log rows; consolidation; chat failure and week
  switching in the real Streamlit app.
- Also includes the Phase 1 follow-up: retrieval no longer asks a course store for more
  results than it holds (the "Number of requested results" warnings).

### Still open (later phases)
- Session tokens are issued but not validated server-side (fixed in Phase 3).
- Passwords use PBKDF2 at 100k iterations (fixed in Phase 3).
- Chat sends the question without the earlier conversation (fixed in Phase 3).
- The academic-calendar tool still has 2025 term dates; no flow uses it yet.

## Phase 1: Fix the adaptive loop

The Streamlit app looks the same; what changed is whether adaptation actually happens.
Research-relevant behaviour changes are marked **(research)**.

### Learner state
- **(research)** ZPD and accuracy A are now the mean correctness of the learner's last
  four graded responses, as the papers describe. Before, the orchestrator read mastery
  from the wrong level of the tool response and always used 0.5.
- **(research)** Mastery updates now persist. Quiz answers and tutor responses are
  recorded after grading (`record_graded_response`), with the learning objective and week
  looked up in the KC model. Chat is ungraded and no longer tries to update mastery.
- **(research)** One cognitive-load formula for every mode. Q counts this session's
  interactions (it previously used lifetime totals in one formula and a tenth of them in
  the other).
- **(research)** Scaffolding fading removes one support level per `fade_threshold`
  consecutive correct answers on the current learning objective and holds while the
  streak lasts. It previously counted calls, lasted one turn and lived in process memory.
- Motivation's performance and streak inputs come from graded answers instead of
  context keys the UI never sent.
- Cognitive-load and scaffolding decision logs are written again (they had 0 rows).
- **(research)** Mastery: new evidence keeps at least half weight after many
  interactions (after about 18 interactions it fell below 0.05, freezing mastery); week mastery can go down;
  stored mastery no longer expires after 14 days.
- **(research)** Week completion is recomputed from the KC model using each objective's
  own `mastery_threshold`. The live app used to add 1/11 per correct quiz answer.

### Grading
- Multiple-choice and true/false answers are checked exactly, without the model.
- Free-text answers are graded by the model with a JSON verdict. The student's text (and
  the tutor question it answers) is sent as quoted data, and tag look-alikes in it are
  neutralised, so it can't rewrite the rubric.
- If grading fails, the answer is marked "couldn't grade", the student is told, and it
  doesn't count. Previously, failures were marked correct.
- **(research)** Tutor responses are graded against the objective. The old keyword
  grader compared KC tags such as `ai_basics` literally, so in practice it scored answer
  length, and a 66-word answer with no relevant content counted as correct.
- **(research)** The tutor advances on a graded correct answer that meets the objective's
  own mastery threshold (from the KC model), or on a graded correct answer after three
  attempts at the objective.
- **(research)** The reply to the tutor's opening "what do you already know?" question is
  diagnostic: it can move the learner on if it already shows mastery, but it isn't
  recorded as evidence. Only a bare "I don't know" skips the grader; "not sure, but I
  think..." is graded.
- Motivation changes feedback wording only; it no longer adds 0.1 to scores.

### Course awareness
- Course profiles (`data/course_profiles/<CODE>.json`) state whether code questions are
  allowed. A course without a profile gets none. Quiz prompts no longer use
  machine-learning examples for every course.
- **(research)** Retrieval discovers every course store on disk, so DEMO101 is now
  searched. Tutor mode's course-content lookup used an API ChromaDB 0.6 removed and a
  different embedding model from the one the store was built with; it now uses the same
  retrieval as Chat.
- An unknown course is an error instead of silently loading a built-in ML model.
- KC generation: "ai"/"ml" misconceptions no longer attach to words like "brain";
  Bloom's "synthesis" and "evaluation" map to Create and Evaluate respectively; the
  generated model is installed where LEA reads it.

### Robustness and setup
- The login page names the missing or wrong setting (`OPENAI_API_KEY`, `REDIS_URL`).
- Registration keeps its confirmation visible; usernames are validated.
- Switching mode during a quiz asks for confirmation (it used to crash) and ends the quiz.
- The week selector shows the learner's stored week after login and after week
  advancement (it always reset to week 1).
- The tutor reports completion after the last objective instead of raising an error,
  and starts (and opens the conversation) at the first objective not yet mastered.
- Quiz questions that fail validation are regenerated once, then skipped (including the
  first question); the question counter follows the real position.
- Course codes are validated before reaching file paths (fixes path traversal in ingestion).
- Retrieval failures are reported instead of "success with no results".
- `scripts/redis_keepalive.py` for free Redis Cloud databases; local Redis options in
  `docs/SETUP.md`.
- `data_foundation/verify_rag_content.py` rewritten as a working command.
- One helper runs async code from Streamlit, one thread per call so sessions never queue
  behind each other; `nest-asyncio` removed.
- Data paths (KC models, mastery backups, logs, ingestion) all resolve through
  `LEA_DATA_DIR` or the repository's `data/` folder.
- Tests: 100, including a scripted DEMO101 session and a headless run of Quiz, Tutor
  and Chat through the real Streamlit app. They run on an in-process Redis and a copy
  of `data/`.

### Still open (later phases)
- Session tokens are issued but not validated server-side (Phase 3, with the API).
- Read-modify-write races on Redis state; memory-consolidation task duplication (fixed in Phase 2).
- Passwords use PBKDF2 at 100k iterations (Phase 3: argon2id, rate limiting).
- The academic-calendar tool still has 2025 term dates; no flow uses it yet.

## Phase 0: Stabilise the repo

Behaviour is intentionally unchanged apart from one crash fix and the UI title.

### Repository
- Runtime logs (`data/decision_logs`, `data/motivation_logs`), simulation checkpoints and
  course-onboarding intermediates are gitignored, and `data/kc_models` is an
  allowlist so private course data can't be committed by accident.
- The code behind the published papers is kept in the first public repository
  (tag `v1.0-snsc`), not in this one.
- Deleted unused modules: `simple_quiz_system-Copy1.py`, `tutor_state.py`,
  `conversation_templates.py`, `mastery_service.py`, `local_fallback.py`,
  `icon_manager.py`, an unused stylesheet and `security_audit.py` (replaced by
  a secret scanner in CI).

### Dependencies
- `pyproject.toml` now lists the packages `src/` actually imports, with `ingest`,
  `eval` and `dev` extras. Previously missing packages are declared (`ddgs`,
  `openai-whisper`, `ragas`, `datasets`).
- `requirements.txt` and `requirements-dev.txt` are universal lock files that keep
  the versions LEA was deployed with (openai 1.61.1, streamlit 1.42.0, torch 2.6.0,
  chromadb 0.6.3). The old file could not be installed because of an httpx conflict.

### Code
- Removed 57 unreachable functions and classes from `streamlit_app.py`
  (6,353 → about 3,830 lines), including superseded quiz-submit and tutor-submit
  variants.
- Replaced all 657 `print()` calls in `src/` with module loggers. The console is
  quiet at the default `LOG_LEVEL=INFO`; set `LOG_LEVEL=DEBUG` for the full trace.
- Log output masks API keys and Redis passwords, and no longer includes partial keys,
  environment variable names or login session tokens.
- Fixed a `NameError` in the debug page's progress repair.
- Login page title now reads "Learning Engagement Assistant", matching the papers.

### Tooling
- Tests (`pytest`): module imports, DEMO101 assets, registration and login, and a
  headless Streamlit smoke test that registers, logs in and renders the main view.
  They run against an in-process Redis and never call OpenAI.
- GitHub Actions: ruff (errors-only rules), tests, and gitleaks over full history.

### Known issues carried into Phase 1
All resolved in Phase 1 except server-side session validation, which moves to Phase 3.
