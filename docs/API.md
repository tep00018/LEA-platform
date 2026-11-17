# LEA HTTP API

The API serves the same services as the Streamlit app, for the Flutter app and any other
client. The full specification is `docs/api/openapi.json` (regenerate it with
`python scripts/export_openapi.py`), and a running server shows interactive docs at
`/docs`.

## Running it

From the repository root, with the same `.env` as Streamlit:

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8100
```

- `http://127.0.0.1:8100/health` should return `{"status": "ok", "redis": true}`.
- To reach it from other devices on your network, use `--host 0.0.0.0` and allow port 8100
  through the Windows firewall when asked.
- Streamlit and the API can run at the same time; they share Redis, so a quiz started in
  one continues in the other.
- Browsers may call the API from any `localhost` port (the Flutter web dev server). Add
  other addresses in `.env`: `LEA_CORS_ORIGINS=https://lea.example.org,http://192.168.1.20:5100`.

## Authentication

1. `POST /auth/register` with `{username, full_name, password, courses}`.
2. `POST /auth/login` with `{username, password}` returns `{token, expires_in, user}`.
3. Send `Authorization: Bearer <token>` on every other request.

The server stores only a hash of each token. A token lasts 12 hours from its last use and
7 days at most, and `POST /auth/logout` ends it at once. Identity always comes from the
token, never from the request body, so one student can't read or change another's data.
Course endpoints check enrolment (403 otherwise).

Passwords are hashed with argon2id. Accounts created before Phase 3 (PBKDF2) keep working
and are upgraded the first time the student logs in.

**Enrolling in another course after registration**: `courses` at registration only sets the
account's first course(s) -- an existing account adds or drops courses with `POST
/me/courses` `{code}` (idempotent) and `DELETE /me/courses/{code}` (both `[CourseOut]`, the
account's own current list; un-enrolling doesn't delete progress in that course, so
re-adding it later resumes where it left off). An admin can do the same for any account:
`PUT /admin/users/{username}/courses/{code}` and `DELETE` the same path (`AdminUserOut`).
Both self-service and admin-driven changes are recorded in the event log.

## Limits

| What | Limit | Response |
|---|---|---|
| Login attempts for one username from one address | 5 per 15 minutes | 429 with `Retry-After` |
| Login attempts for one username from anywhere | 50 per 15 minutes | 429 |
| Failed logins from one address | 100 per 15 minutes | 429 |
| New accounts from one address | 60 per hour | 429 |
| Model-backed actions (chat, tutor replies, quiz start/answer/next) | 30 per user and 300 per address, per minute | 429 |
| Text of a question, answer or reply | 4,000 characters (after trimming spaces) | 422 |

A successful login clears that username's counters. The per-address limits are generous
because a class can share one address. Someone guessing from one device locks the
username only on that device; the student can still log in elsewhere.

If LEA runs behind a proxy or tunnel, start uvicorn with
`--proxy-headers --forwarded-allow-ips <proxy address>` so limits see the real client
address; otherwise every request appears to come from the proxy.

## Account admin

There is no self-service password reset yet. Whoever runs LEA can use:

```bash
python scripts/manage_account.py reset-password alice   # asks for the new password
python scripts/manage_account.py deactivate alice        # also ends alice's sessions
python scripts/manage_account.py activate alice
python scripts/manage_account.py sign-out alice          # end every session
python scripts/manage_account.py make-admin alice        # also make-teacher, make-student
python scripts/manage_account.py set-kind alice test     # tag activity as test (see docs/SETUP.md)
python scripts/manage_account.py delete alice            # the account and all its data (asks first)
```

## Roles

Every account has a `role`, returned by `/me`: `student` (the default), `teacher` or
`admin`. Teachers see the Teacher area (`/teach/...`) for the courses they own; admins see
every course and manage accounts and ownership (`/admin/...`). There is no self-service
teacher sign-up: make the first admin with `manage_account.py make-admin`, then create
teachers with `POST /admin/users`.

Every `/admin` route answers 403 (`NotPermitted`) to anyone but an admin, and every
`/teach` route to students; `/teach/courses/{code}` also needs the caller to own the
course (or be an admin), and answers 403 the same way whether or not the course exists.
Admin and teacher actions are recorded, with the actor's username, in the event log.

## Course onboarding (Teacher area)

1. `POST /teach/courses` `{code, name, discipline, allows_code, code_language, weeks}`: a
   teacher who creates a course owns it. Students don't see it until a KC model is
   published for it.
2. `PUT /teach/courses/{code}/objectives` with every week's title and learning objectives
   (full sentences, 1-12 per week).
3. `POST /teach/courses/{code}/uploads` (multipart): PDF, DOCX, PPTX, XLSX, MD, TXT, IPYNB,
   MP3, MP4, WAV; 50 MB per file, 1 GB per course. Files are checked by extension and by
   content. They are stored in `data/course_uploads/<CODE>/` and never committed.
4. `POST /teach/courses/{code}/jobs` prepares a run and prices it (`estimate.usd`, per step,
   with notes); nothing runs until `POST /teach/jobs/{id}/confirm`. Steps: `convert`
   (uploads to LEA's `WeekNN-KindX-Title` files), `transcribe` (audio and video, with
   Whisper on this PC), `embed` (chunk and embed; unchanged files are skipped, deleted
   uploads leave the index), `kc_draft` (GPT-4o drafts granular objectives from the
   weekly objectives), `profile`, `verify` (searches the content with each objective and
   flags weak support). One job per course at a time (409); a job left running when LEA
   stopped is marked failed at the next start.
5. Poll `GET /teach/jobs/{id}` for `status`, `step`, `percent` and `log`. The KC model it
   drafts is saved under `data/kc_models/<CODE>/drafts/` with each objective's best
   matching excerpt; it is **not** published (see KC review below).

## Linked materials sources

A course can link a read-only folder of materials instead of (or alongside) uploading
files one at a time. Folders live under `LEA_COURSE_MATERIALS_ROOT` (`.env`; default
`~/Documents/LEA/course_materials`), one subfolder per course code.

- `GET /teach/materials-folders`: the root's subfolder names, for a "link a folder" picker.
- `GET /teach/courses/{code}/materials-source`: the current link (`{type: "folder", path}`)
  or `null`.
- `POST /teach/courses/{code}/materials-source` `{type: "folder", path}`: link a folder
  under the root. `path` must resolve inside the root (no `..`, no absolute path, no
  symlink leading outside it); the folder must exist.
- `DELETE /teach/courses/{code}/materials-source`: stop tracking the link. Files already
  ingested from it stay as ordinary uploads.
- `GET /teach/courses/{code}/materials-source/sync-preview`: what the next Build job would
  pick up, read-only. Each candidate file is `new`, `changed` (content differs from what
  was last ingested), `unchanged` (skipped), `removed` (its file is gone from the folder,
  so its upload will be deleted), or `rejected` (with why -- wrong file type, over the size
  limit, or a symlink leading outside the root). A folder whose name starts with `_` (e.g.
  `_teacher`), and any hidden file or folder, is never offered as a candidate at all --
  not listed, not rejected, simply invisible.
- `POST /teach/courses/{code}/jobs` (the same Build job as above) reconciles a linked
  folder's current files into the course's uploads *before* pricing, so the estimate and
  every later step (convert, embed, ...) already reflect the linked folder's current
  state, no additional endpoint or step needed. `UploadOut.linked_relpath` marks an
  upload that came from a linked source rather than a manual upload; uploads keep working
  normally alongside a linked source.
- Link, unlink and sync each go to the event log as a staff action
  (`materials_source_link`/`_unlink`/`_sync`).

Today there is one source type, `"folder"`; the interface
(`src/onboarding/materials_source.py`) is deliberately small (list files, read a file,
fingerprint a file) so a connector to an existing system (Canvas, Moodle, SharePoint,
Google Drive) can be added later without changing this API shape.

## KC review and versions

A course's KC model has published versions (`data/kc_models/<CODE>/versions/v<n>.json`,
never changed once written) and at most one draft. Students use the live version while
the draft is edited.

- Start a draft from the live model (`{"source": "published"}`) or from an onboarding
  job's draft (`{"source": "job:<id>"}`). A draft is a list of rows, one per granular
  objective, with its learning objective and week.
- **IDs:** only LEA assigns them. Leave `go_id` blank for a new objective, and `lo_id`
  blank for a new learning objective (rows with the same week and objective text share
  it). IDs never change and are never reused: an objective removed from the model is
  retired. A new row with `split_from` replaces a published objective (several rows can
  split one); a row with `merged_from` replaces two or more.
- **Checks** (`PUT` refuses to save with any error; `validate` only reports): IDs
  unchanged or blank, no duplicates, no retired ID back, Bloom level one of Remember,
  Understand, Apply, Analyze, Evaluate, Create, mastery thresholds 0.5-0.95,
  prerequisites (GO IDs) exist and don't go round in a circle, every week has objectives,
  a learning objective's rows share one week and one text. A prerequisite taught after
  the objective that needs it is a warning.
- **Spreadsheet:** `export` gives an XLSX with the ID columns locked, 200 empty rows for new
  objectives and a "Read me" sheet; `import` validates it and, only if it has no errors,
  replaces the draft. The response lists every change.
- **Publish:** `diff` shows the changes and how many students have mastery on objectives
  that are retired, split or merged. Publishing writes the next version, makes it live at
  once for every process (API and Streamlit reload a changed model), and **(research)**
  carries mastery along the lineage: each part of a split gets the old objective's
  mastery, a merge the mean of the sources the student had. Retired objectives keep their
  mastery but no longer count. A draft started before another version was published
  can't be published (409). How many objectives were edited, added and removed, the
  number of saves and the review time go to the event log.
- A course that predates versioning shows its model as version 0; its first publish
  records it as v1 and publishes the draft as v2.

## Content audit

`POST /teach/courses/{code}/audit/runs` checks the live version and returns findings, not
scores, ranked by severity (and, within a check, by how many items a finding covers),
at most 15 per check. Each finding has a stable `key`, its evidence, what it points at
(`target`: a file, objective, question or week) and an evidence `tier`:

| Check | Tier |
|---|---|
| Accessibility: pictures without real alt text (PowerPoint, Word), low contrast where both colours are set, slides without titles, Word files without headings, PDFs without a text layer, recordings without captions | `well_supported` |
| Question writing in the reference bank: negative stems, all/none of the above, longest option correct, stem words only in the right option | `well_supported` |
| Prerequisite taught after the objective that needs it | `rule_based` |
| Bloom balance per week (a distribution) | `moderate` |
| Coverage (each objective's best retrieval match, cut-off calibrated per course), redundancy between objectives, objectives without reference questions | `experimental` |
| Readability and slide density | `informational` |

Accept or dismiss a finding with `PUT .../audit/findings/{key}` (a note is optional);
decisions are kept by key, so they carry over to later runs. The latest run marks what is
`new` since the one before and lists what was resolved. Only coverage and redundancy use
OpenAI (embeddings, well under a cent: `GET .../audit/estimate`); if they can't run the
others still do, and the run says so in `skipped`. Runs and decisions go to the event log.

## Student analytics

`GET /teach/courses/{code}/analytics` summarises each objective from the event log, most
in need first: its mastery band, how many students have graded answers, first-attempt
accuracy, attempts to master, the learning-curve verdict and a "needs attention" score
with the factor that drove it. Usage (active students, sessions, chat questions, hours)
comes last. Filters: `week`, `since`, `until`.

- **Who counts.** `kind=real` (the default) or `kind=simulated` (seeded students, for trying
  the screens); the two are never mixed. Test accounts and preview sandboxes are never
  included, and neither are staff actions.
- **Fewer than 5 students.** Any figure based on fewer than 5 students is withheld
  (`null`, `suppressed: true`); the band is then `insufficient`. The same rule applies to
  each learning-curve point, wrong answer and chat topic.
- **Definitions.** A student's estimate for an objective is the mean of their last three
  graded scores. The band is `mastered` when at least 60% of students are at or above the
  threshold, `struggling` when at least 40% are 0.25 or more below it, otherwise
  `developing`. Attempts to master counts graded answers until the last three reach the
  threshold. The learning curve is the error rate at each opportunity (1st, 2nd, ... graded
  answer); its verdict is `declining` (learning), `flat` or `rising`.
- **Needs attention** is LEA's heuristic, not a validated measure: low first-attempt
  accuracy (35%), a flat curve (30%), tutor struggle (20%) and chat questions (15%).

`GET .../analytics/objectives/{go_id}` adds the curve (and `course_curve`, every objective pooled), the most common wrong answers (quiz
options, grouped by objective because each student's questions are generated), tutor
struggle (3+ wrong in a row, video help shown, sessions left while stuck), chat topics and
a suggested action. Suggestions are drafts for the teacher; LEA never changes anything.

`GET .../analytics/curves.csv` exports the learning curves, aggregated (no per-student
rows). `GET .../analytics/chat-topics` returns the last topic grouping and what a new one
costs; `POST` runs it (GPT-4o mini, two independent passes, reporting their agreement;
only topics asked by 5 or more students are kept). The questions sent are pseudonymous and
have had names removed. `POST .../analytics/objectives/{go_id}/explainer` drafts a short
explanation from the course material for the teacher to edit. Each view is logged as a
staff action.

## Videos for stuck students

When a student gets three answers in a row wrong on an objective, the tutor adds a short
list of videos to its reply, **once per stuck streak** (not on every wrong reply after it; a
correct answer or a new objective resets the streak). Where the list comes from, in order:

1. **The instructor's videos** for that objective (below), in their order and with their
   notes; the first three are shown. No search, no quota.
2. **An automatic YouTube search** (needs `YOUTUBE_API_KEY`). Each objective is searched at
   most once a week: results are cached in Redis, and after a quota error no search is sent
   until YouTube's daily quota resets at midnight Pacific.
3. **Generic search links**, when neither is available.

The tutor's `answer` events record `youtube_shown` and `youtube_source` (`curated`,
`search:api`, `search:cache`, `search:search-link` or `fallback`).

## Mastery in the event log (2026-11-03)

Every graded answer on an objective also writes a `mastery_change` event (the objective's mastery level before
and after, its threshold, whether it is mastered, and the same for its learning objective), with `go_id` and
`lo_id` set. When an objective or a learning objective crosses its threshold, a `mastery_milestone` event says
`mastered` or `lost` (`scope` is `go` or `lo`). A learning objective counts as mastered when every objective in it
is at or above its own threshold. Ungraded answers write neither. These are the durable record a learner profile
is rebuilt from; they go to the research export like other learner events.

Instructor endpoints (teacher who owns the course, or admin):

| Endpoint | Purpose |
|---|---|
| `GET /teach/courses/{code}/videos` | Every objective of the live version with its videos, what a stuck student gets for it (`student_gets`: `curated`, `search` or `links`), and `help_shown_students` (real students shown video help there in the last 30 days: 0 if none, `null` for 1 to 4, withheld as in Analytics); plus `help_shown_times` (`null` below 5 students) and `search`: whether automatic search is configured, `quota_paused_until`, and how many searches are cached |
| `POST /teach/courses/{code}/videos` | `{go_id, url, note}`: add a video (up to 5 per objective). The link may be `watch`, `youtu.be`, `embed`, `shorts` or `live`. YouTube's public oEmbed check confirms the video is public and supplies its title and channel (no API key or quota); a private, removed or non-embeddable video is refused. `note` (up to 200 characters) is shown to the student |
| `DELETE /teach/courses/{code}/videos/{go_id}/{video_id}` | Remove a video |
| `POST /teach/courses/{code}/videos/{go_id}/{video_id}/move` | `{direction: "up" or "down"}`: reorder (the first three are shown) |

Lists are stored per course in `data/course_videos/<CODE>.json` (gitignored), keyed by GO ID,
so they stay attached to an objective through later KC versions. Every change is a logged
teacher action (`video_add`, `video_remove`, `video_reorder`).

## Try as a student (preview)

`POST /teach/courses/{code}/preview` creates or reuses the teacher's sandbox account,
`<teacher>.preview` (nobody can log in to it; its password is random), enrols it in the
course and returns a token for it. The app uses that token for the student endpoints
(Chat, Tutor, Quiz, progress) and the teacher's own token for `/teach` and `/admin`. The
sandbox is tagged `test` from the start: its activity never reaches research logs,
analytics or exports. It uses the published version of the course.

After each preview turn, `GET .../preview/explain` (teacher token) shows why LEA did what
it did: the objective, mastery before and after against its threshold, grading, ZPD,
cognitive load, motivation, scaffolding and the course content retrieved. Student
responses never carry this. `GET .../preview/probes?week=N` lists things to try, and
`POST .../preview/reset` forgets what the sandbox did in the course.

## Endpoints

| Method | Path | Does |
|---|---|---|
| POST | `/auth/register` · `/auth/login` · `/auth/logout` | Accounts and tokens |
| GET | `/me` · `/me/courses` | The student and their courses |
| GET | `/courses` | Courses open for registration (no login) |
| GET | `/courses/{code}/outline` | Weeks and learning objectives |
| GET | `/courses/{code}/progress` | Current week and its completion |
| GET | `/courses/{code}/mastery?week=N` | Each objective's mastery against its own threshold |
| GET · DELETE | `/chat/{code}/messages` | Chat history for the course; clear it |
| POST | `/chat/{code}/messages` | Ask a question `{text, week}` |
| POST | `/chat/{code}/messages/stream` | Same, streamed (see below) |
| GET · POST · DELETE | `/quiz` | Current quiz; start `{course, week}`; forget it |
| POST | `/quiz/answer` · `/quiz/next` · `/quiz/end` | Answer, move on, stop early |
| GET · POST | `/tutor` | Current tutor session; start `{course, week}`, or `{course, week, review_quiz: true}` to review a finished quiz on that week (`quiz_review` in the answer says whether it did). A review teaches only the objectives the quiz got wrong; an ordinary start teaches only the week's objectives below their mastery threshold; a week that is already fully mastered returns a session that is already `completed`, with a message offering a refresher or moving on, and advances the learner as finishing the tutorial would |
| POST | `/tutor/replies` · `/tutor/replies/stream` | Reply to the tutor `{text}` |
| POST | `/tutor/end` | End the session; returns a summary |
| GET · POST | `/teach/courses` | Teacher: the courses I own (admin: every course); set up a new course |
| GET | `/teach/courses/{code}` | Teacher: a course I own: weeks, objectives, content, owners, uploads, active job |
| GET · PUT | `/teach/courses/{code}/objectives` | Teacher: the weekly learning objectives the KC model is drafted from |
| GET · POST | `/teach/courses/{code}/uploads` | Teacher: list; upload files (multipart `files`, optional `week`, `kind`) |
| DELETE | `/teach/courses/{code}/uploads/{name}` | Teacher: delete an upload |
| GET · POST | `/teach/courses/{code}/jobs` | Teacher: recent jobs; prepare and price an onboarding run `{steps?}` |
| GET | `/teach/jobs/{id}` | Teacher: a job's status, progress, estimate, result and latest log |
| POST | `/teach/jobs/{id}/confirm` · `/teach/jobs/{id}/cancel` | Teacher: accept the estimate and run it; cancel |
| GET | `/teach/courses/{code}/kc` | Teacher: published versions and the draft |
| POST · GET · PUT · DELETE | `/teach/courses/{code}/kc/draft` | Teacher: start a draft `{source}`; read it; replace its rows; discard it |
| POST | `/teach/courses/{code}/kc/draft/validate` | Teacher: check rows without saving |
| GET · POST | `/teach/courses/{code}/kc/draft/export` · `/import` | Teacher: the draft as XLSX; read an edited XLSX back |
| GET | `/teach/courses/{code}/kc/diff` | Teacher: what publishing would change, and how many students it affects |
| POST | `/teach/courses/{code}/kc/publish` | Teacher: publish the draft as the next version `{note}` |
| POST | `/teach/courses/{code}/preview` · `/preview/reset` | Teacher: a token for your sandbox student account; start it over |
| GET | `/teach/courses/{code}/preview/explain` · `/preview/probes` | Teacher: why LEA did what it did on your preview turns; things to try |
| GET | `/teach/courses/{code}/audit` · `/audit/estimate` · `/audit/runs` | Teacher: the latest audit with decisions; its cost; past runs |
| POST | `/teach/courses/{code}/audit/runs` | Teacher: audit the live version |
| PUT | `/teach/courses/{code}/audit/findings/{key}` | Teacher: `{status: accepted\|dismissed\|open, note}` |
| GET · POST | `/admin/users` | Admin: every account; create a teacher `{username, full_name, password, role}` |
| PATCH | `/admin/users/{username}` | Admin: `{role}`, `{active}` (deactivating signs the account out everywhere) or `{session_kind}` (`test` keeps it out of research data) |
| GET | `/admin/courses/{code}/owners` | Admin: a course's owners |
| PUT · DELETE | `/admin/courses/{code}/owners/{username}` | Admin: add or remove an owner (teachers and admins only) |
| GET | `/health` | Redis reachable? |

Learning objective titles in `/outline` and `/mastery` are display names: a KC model's
`short_title` when it has a real one, otherwise the full objective. The full objective
stays in the model for LEA's own prompts.

A student has at most one quiz and one tutor session at a time. Starting one on the week
it's already on returns it (so a client can always call start to resume).

### Quiz

`QuizView.status` drives the screen:

- `question`: show `question` (`type` is `multiple_choice`, `true_false`, `fill_in_blank`
  or `open_ended`; `options` for multiple choice). The answer is never sent to the client.
- `feedback`: show `feedback` (`correct` is `null` when the answer couldn't be graded; it
  then doesn't count), then call `/quiz/next`.
- `completed`: show `results`. `advanced_to_week` is set if the student moved on a week.
  Each result has the `go_id` of the objective it tested (names are in `/mastery`).

Answering twice, or calling `next` before answering, returns 409.

**Reference question banks in Quiz mode** *(research)*: for a multiple-choice or true/false
question, if the course has a reference question bank
(`data/course_sources/<CODE>/question_bank.json`, `format: "lea-reference-question-bank/1"`)
with an entry tagged to that exact `go_id` and type, marked `tagging.reviewed: true`, one of
those is used verbatim instead of generating a question with a model -- no model call is
made for that turn. A GO with no reviewed, type-matching bank entry is unaffected: it still
generates as before. The client sees no difference either way (same `QuestionView` shape;
provenance isn't exposed over the API). `tagging.reviewed` defaults to `false` when a bank
is auto-tagged (e.g. by embedding similarity at course build time) -- a course's bank
contributes nothing here until an instructor reviews and flips entries to `true`.

### Tutor

`TutorView` is the session: `objective_index` of `objectives_total`, the `current_objective`,
`messages`, and how the tutor is supporting the student: `scaffolding_strategy`
(`conceptual`, `procedural`, `strategic`, `metacognitive`) and `scaffolding_level`
(`very_high` to `minimal`). The first reply answers the opening "what do you already know?"
and is never graded; after that, `TutorReplyOut.graded` and `correct` say whether a reply
counted and how it went. When `completed` is true, `advanced_to_week` says whether the
student moved on a week.

`TutorView` also carries `current_objective_mastery`, `cognitive_load` and `zpd_score`
(all nullable) -- debug/monitoring fields for testing by hand, refreshed on every
start/reply so a plain `GET /tutor` between turns still has something to show. These are
temporary and may be removed once manual testing of the tester configuration (2026-09-27)
is done; a client should treat missing values as "not shown" rather than an error.

## Answer timing and cognitive load (optional)

`POST /tutor/replies`, `/tutor/replies/stream` and `/quiz/answer` accept an optional `timing` object:
`response_ms` (question shown to answer submitted), `typing_ms`, `chars`, `prompt_chars`, `elapsed_ms` (time on
task so far), `hint_requested`, and `effort_rating` (-2 much easier to 2 much harder than the last objective).
A client that omits it changes nothing. LEA's default cognitive-load equation is unchanged; with `timing` sent,
the personalised equation (`src/core/cognitive_load.py`) is also computed and logged with each turn's
`cognitive_state.load_details`. Set `LEA_COGNITIVE_LOAD_MODEL=personal` to let it drive scaffolding (research;
off by default).

**Motivation no longer moves the support level (2026-09-27).** LEA still classifies each turn's motivation state
(cold start, drop, plateau, maintained high) and still uses it for feedback tone and messages, but it no longer
raises or lowers the scaffolding level (`LEA_MOTIVATION_SUPPORT`, now `off` by default). A simulation study found
the previous behaviour classified about 90% of tutor turns as a "motivation drop" (driven mainly by recent
accuracy against a noisy grader) and that this shifted support far more than the ZPD or cognitive-load rules did.
Set `LEA_MOTIVATION_SUPPORT=on` to restore the old behaviour. `LEA_MOTIVATION_CLASSIFIER` (whether recent accuracy
counts toward calling a drop) is unchanged, still `current` by default.

## Free-text grading (2026-09-27, updated with the researcher's adjudication)

The tutor's and quiz's free-text grader (`src/core/grading.py`, "V5") judges an answer only against the specific
question actually asked; accepts a brief, otherwise-complete answer without requiring every part of a multi-part
message; accepts fill-in synonyms and paraphrases; marks an answer incorrect if it contradicts the reference or
lesson passage; and still credits an answer that correctly answers the question even if it also makes an
unrelated wrong side remark, correcting that remark in the feedback instead of marking the whole reply wrong. It
also asks whether the question was checkable at all -- a reply to something like "are you ready to continue?" is
left ungraded (it never counts as right or wrong, and never affects mastery) instead of being scored against the
objective's reference material. Chosen from an offline replay against 1,108 saved answers from earlier pilot
runs, scored against the simulator's known intent (`simulation/grader_replay.py`) and refined against a 25-item
blind researcher review of the disagreements (see CHANGELOG.md for the numbers). Pass `with_confidence=False` to
`grading.grade_with_llm` for the original, ungated grader.

## One recorded question per tutor turn (research, 2026-09-27, on by default)

Unless `LEA_TUTOR_RECORDED_QUESTION=off` (the default is on, with `LEA_TUTOR_QUESTION_SCOPE=broad`), the tutor's reply generation is told to end its message with exactly
one clear, checkable question about the current objective (an earlier exploratory question is allowed but
must be labelled optional), to state only facts the course content given to it supports, and to keep the
reply to about 200 words. The reply is streamed to the student exactly as before. When the student's next
reply arrives -- not when the tutor's message was generated, so this adds no latency to the tutor's turn and
costs nothing if the student never replies -- a separate, non-streamed extraction call records the one
required question from the tutor's last message and confirms it is genuinely about the current GO. Grading
then judges the student's reply against that recorded question, scoped to that GO's reference material,
instead of the raw last tutor message. A turn with no valid recorded question (extraction failed, or the
tutor's question wasn't about the current GO) is left ungraded rather than graded against the wrong thing.
This targets objective drift: a 24% drift rate was measured in an offline simulation study before this
change (`simulation/runs/grader_replay/go_drift.json`). Not yet measured live.

## Streaming

`/chat/{code}/messages/stream` and `/tutor/replies/stream` return `text/event-stream`:

```
event: token
data: {"text": "Supervised learning "}

event: token
data: {"text": "uses labelled data."}

event: done
data: {"ok": true, "message": "Supervised learning uses labelled data."}
```

`done` carries the same body as the non-streaming endpoint; show the tokens as they arrive,
then replace them with `done`'s message. On failure the last event is
`error` with `{detail, code, status}`.

## Errors

Every error is JSON `{"detail": "...", "code": "..."}`, including validation errors and
unexpected failures (500, `InternalError`). `detail` can be shown to the student.
`Retry-After` and `WWW-Authenticate` are readable from browser code.

| Status | code | When |
|---|---|---|
| 400 | `InvalidInput` | Wrong course, week or input |
| 401 | `NotAuthenticated` | Missing, unknown or expired token |
| 403 | `NotEnrolled` | Course not in the student's enrolment |
| 404 | `NoActiveSession` | No quiz or tutor session to act on |
| 409 | `WrongState` · `Busy` | Out of order, or the previous request is still running |
| 422 | (validation) | Body doesn't match the schema |
| 429 | `RateLimited` | See Limits; honour `Retry-After` |
| 503 | `Unavailable` | The model or retrieval failed; try again |
