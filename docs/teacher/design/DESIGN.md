# LEA Teacher module: design spec (Chalkboard)

**Status: proposal for the researcher's approval (B8 checkpoint). Nothing here is built yet.**

The teacher screens use the student app's design system unchanged: colour tokens, type,
radii and components from `docs/design/DESIGN.md`. The screenshots in `screens/` are the
reference; `mockup.html` is the interactive mockup they were taken from (open it in a
browser to switch screens and light/dark). Names, numbers and findings in them are
illustrative.

Screenshots: `<screen>-desktop-<theme>.png` for screens `home`, `setup`, `kc`, `publish`,
`videos`, `videos-edit`, `audit`, `analytics`, `detail`, `preview`, `admin`; themes `light` and `dark`; 1224 px wide.

## Where it lives

- Routes under `/teach/...` and `/admin/...` in the Flutter app, shown only to accounts whose
  `/me` role is `teacher` or `admin`. Students never see an entry point.
- **Entry:** in the student rail, a "Teaching →" link under "Your progress" (staff only).
  Inside the Teacher area the rail swaps to the teaching navigation and ends with
  "Back to learning →", so moving between the two is one click either way.
- **Wide screens first** (≥ 720 px, as the student app). Teachers work at a desk. On a phone
  the Teacher area is read-only: course list, job progress, analytics and findings;
  editing, uploads and publishing say "Open LEA on a computer to edit".
- Streamlit stays student-only.

## Rail (teaching)

Top to bottom: LEA avatar + "LEA" + "Teaching"; course picker (courses the teacher owns,
"All courses" for the home and admin screens); navigation with 18 px line icons:
**Courses, Setup and materials, Objectives, Videos, Content audit, Analytics, Try as a student**;
an "Admin" group with **Users and owners** (admins only); spacer; "Back to learning →";
user row with the role under the name ("Teacher · Admin · Log out"). Small counts sit at
the right of a nav item: "Draft" when the course has a KC draft, the number of open
findings on Content audit. Active item: `surface-2` background, 600 weight.

## Screens

Each screen has the same header band: an uppercase kicker ("AIML101 · Objectives"), a
title (Bricolage 24 px), one line of context in `muted`, and actions on the right (one
primary button at most).

### 1. Courses (`home`)
One card per course: state pill (**Live · version N** in `success-soft`, **Live · before
versioning** outlined, **Setting up** in `accent-soft`), owners, code and name, three stats
(students, weeks, objectives), one attention line and the one or two next actions.
- A course in setup shows its build progress and "Students can't see this course until
  you publish its objectives."
- Attention lines come from analytics ("3 objectives need attention · Week 5"). Below 5
  students: "Analytics start at 5 students. 4 so far."
- "Recent activity" lists the course's staff actions from the event log's audit trail.
- Primary action: **New course** (code, name, discipline, Python code questions on/off
  and language, number of weeks).

### 2. Setup and materials (`setup`)
Left: **Materials** (upload button, drop zone, table of file, week, kind, size and state:
Staged, Transcribing…, Waiting, or a problem in `danger`) and **Weekly learning
objectives** (summary with Edit; the editor is a simple list per week, full sentences).
Right: the **Build** card.
- Before a build: the price per step, total, and **Start build · $0.41** / **Not now**.
  Nothing runs or is spent until the teacher starts it.
- While it runs: status pill, current step and file count with a meter, the six steps as
  a checklist (done ✓ on `primary`, current • on `accent`, to-do outlined), the last few
  log lines (mono, on `bg`), the estimate and who started it, and **Cancel after this
  file** (danger outline).
- Afterwards: "Draft ready: review the objectives →" (success), or the error in plain words
  with **Try again**.

### 3. Objectives (`kc`)
Header: "Objectives: draft", "Based on version 2 · saved 2 minutes ago · 6 edits", actions
**Export to Excel**, **Import**, **Discard draft**, primary **Review changes**. With no
draft, the title is "Objectives: version 2 (live)" and the primary action is **Edit**.
- Week tabs, then one card per learning objective: its ID (mono, muted), text and short
  title, and a table of its granular objectives: name + ID, Bloom pill, threshold,
  keywords, content match (the similarity, or "▲ Weak support" in `warning` with the
  matched excerpt under the name).
- IDs are shown, never editable. Rows are edited in place; "+ Add objective", "Split…" and
  "Merge…" at the foot of each card. An edited row has an "Edited" pill; a cell with an
  error is underlined in `danger`.
- Side panel: **Checks** (problems that stop saving, in `danger-soft`; warnings in
  `accent-soft`; each names the row and says what to do) and **Row details** for the
  selected row (description, prerequisites as ID + name pills, the source excerpt).

### 4. Review changes and publish (`publish`)
Counts across the top (added, changed, split, merged, retired, objectives after), then a
table of every change with a coloured pill (Added `success-soft`, Changed `accent-soft`,
Split and Merged `surface-2`, Retired `danger-soft`) and the before → after detail.
Right: **Students affected** (how many of how many, per kind, and what happens to their
mastery in plain words), a **Research note** banner, and an optional note for the version.
Primary action: **Publish version 3**. If another version was published meanwhile:
"Someone published version 3 while you were editing. Start a new draft from it."

### 5. Content audit (`audit`)
Header: number of findings, when and on which version it ran, how many are reviewed;
**Run audit again · ≈ $0.12** shows its cost before running. Filter chips by check, and the
evidence legend. Each finding: a severity bar (danger, warning, muted), a one-line title,
why it matters, the evidence (file and slides, or objective and match), the **evidence
tier** pill (Well supported `success-soft`, Rule-based `success-soft`, Moderate outlined,
Experimental dashed; LLM judgements also say "LLM suggestion"), and **Accept** /
**Dismiss…** (asks for an optional note). Reviewed findings show their decision and note
instead of buttons, and keep it on the next run.

### 6. Analytics (`analytics`)
Filters: week, date range, **Export curves (CSV)**. A summary of bands (struggling,
developing, mastered, not enough evidence) and one sentence saying what "Needs attention"
is. The table: objective + ID, **band** (Mastered `success-soft`, Developing
`accent-soft`, Struggling `danger-soft`, Not enough evidence dashed), students, first-try
accuracy, attempts to master, and **needs attention** with the factor that drove it (a
`danger` dot for high). Usage (active students, sessions, time on task) comes last, never
first. "42 students · real sessions only" is always in the header.
- **Privacy:** any figure drawn from fewer than 5 students shows "< 5" or "Not enough
  students yet"; nothing per student in the first release.

### 7. Objective detail (`detail`)
Learning curve (error rate by practice opportunity; this objective in `danger`, the
course's typical curve dashed `muted`) with a one-sentence reading ("Flat at about 60%:
practice isn't reducing errors"); common wrong answers as meters ("Grouped by objective:
quiz questions are written fresh for each student"); tutor struggle (3+ wrong in a row,
video help shown, left without moving on); what students ask in Chat (paraphrased topics
with counts, only topics 5+ students asked about, names removed); **Suggested action**
labelled "LEA suggestion", with Edit note / Dismiss, and **Draft an explainer** in the
header (drafts text for the teacher to edit; never published by itself).

### 8. Try as a student (`preview`)
The real student app for a sandbox account (`<teacher>.preview`, tagged test).
- A persistent banner on `accent-soft` across the top: "**Preview:** your answers aren't
  recorded as student data · AIML101 · published version 2", with **Reset preview** and
  **Back to teaching**. It can't be dismissed.
- The explain panel on the right (teachers only; the API field is never sent to
  students): objective, mastery before → after against its threshold, grading, ZPD,
  cognitive load, motivation, scaffolding, the course content it retrieved, and a
  checklist of probes for the week ("Answer the first question with 'I don't know'",
  "Give a wrong answer twice", "Ask something off-topic", "Ask for the answer outright",
  "Ask for a hint"), ticked as the teacher tries them.
- The explain panel can be hidden to see exactly what a student sees.

### 9. Users and owners (`admin`)
Accounts table (name + username, role pill, courses owned, status: Active, Deactivated in
`danger`, Test dashed), with search and filters (All, Staff, Test accounts). Right: **Course
owners** (pick a course, remove owners, add a teacher; "Only teachers and admins can own
courses.") and **New teacher account** (name, username, temporary password). Edit opens a
small panel: role, active/deactivated ("Deactivating signs them out everywhere"), test
account on/off. "LEA needs at least one active admin" appears when that's what stops a
change.

### 10. Videos for stuck students (`videos`, `videos-edit`)
*Added for the YouTube-help work; approved by the researcher and built (`videos_screen.dart`,
`video_editor_screen.dart`). The API is `/teach/courses/{code}/videos`, see `docs/API.md`.*

Rail item **Videos** (icon: a play button in a rounded rectangle) between Objectives and
Content audit, with the number of objectives that have videos as its count.

**Overview (`videos`).** Header "Videos for stuck students": "Shown once when a student gets
three answers in a row wrong · 9 of 63 objectives have your videos"; filters: week, and
"Without videos" (All, With videos, Without videos). When automatic search is paused, a
`accent-soft` banner: "**Automatic YouTube search is paused** until midnight Pacific (about 7
hours): Google's daily quota is used up. Your videos are unaffected; objectives without them
show generic search links until then." (from `search.quota_paused_until`); when search isn't
configured, a neutral banner: "Automatic YouTube search isn't set up, so objectives without
your videos show generic search links." A stats card (objectives with videos, without, and
how many times help was shown in 30 days) and one sentence: "Students see the **first three**
videos in your order. Search results for an objective are kept for a week." The table:
objective + ID, **Your videos** ("3 of 5" `success-soft`, "None yet" dashed), **What a stuck
student gets** ("Your videos" `success-soft`; "Search links" `accent-soft` + "search paused";
"Automatic search" outline when search is working), **Help shown** (students shown video help
in the last 30 days, from real sessions only; "< 5" below 5 students, the same rule as
Analytics) and **Edit videos** / **Add videos**. The help-shown column tells the instructor
where students are stuck, so effort goes there. *Counted from the event log, real students only, withheld below 5 (`help_shown_students`,
`help_shown_times`).*

**One objective (`videos-edit`).** Header: objective name, "GO_05_13_003 · 11 students were
shown video help here in the last 30 days", "All objectives". Left: **Your videos** (position
badge; play thumbnail; title; channel and who added it; the note; up, down, Remove; "4 of 5 ·
the first three are shown"; videos after the third are one line, dashed badge, "waits:
students see the first three"), then **Add a video**: YouTube link, optional note (200
characters, with a counter), **Check and add**, and "LEA checks the link with YouTube and
fills in the title and channel." Right: **What a stuck student sees**, a preview of the
tutor's reply with the first three videos and their notes exactly as students get them, and
"Shown once, when a student has three wrong answers in a row on this objective"; and **With no
videos of yours**: "LEA searches YouTube for this objective at most once a week and shows what
it finds. When Google's daily quota is used up it shows generic search links instead.
Choosing videos here avoids both."

Behaviour and copy: adding is one action (paste, optional note, Check and add); the button
says "Checking…" while YouTube is asked. Errors sit under the link field in `danger` with
what to do: "That isn't a YouTube link. Paste the address of a video on youtube.com or
youtu.be." · "That link doesn't point to a single video. Paste the address of the video
itself." · "YouTube can't show that video: it may be private, removed, age-restricted or not
allowed to be embedded. Check the link, or choose another video." · "That video is already in
this objective's list." · "An objective can have up to 5 videos. Remove one first." ·
"Couldn't reach YouTube to check that video. Try again in a moment." Remove asks nothing (it
is undone by adding the link again) but shows "Removed. Add it again" for 8 seconds. Up/down
are buttons with labels ("Move up", "Move down", not arrows alone), disabled at the ends.
Empty objective: "No videos yet. Students who get stuck see a search result instead. Paste
a YouTube link to choose what they see." Every change is logged as a teacher action.
Teachers see and edit only courses they own; on a phone the screens are read-only ("Open LEA
on a computer to edit").

## States every screen needs
Loading (skeleton rows, as the student app), empty ("No findings yet. Run an audit." ·
"No students yet: analytics start at 5."), offline (the student app's banner), 403 ("You
don't teach this course.") and errors in plain words with what to do next.

## Accessibility
As the student app: WCAG AA contrast in both themes, visible focus, 44 px targets on
touch, tables with real headers, status never shown by colour alone (every pill has a
word), charts with a text reading next to them.

## Decisions for the owner
1. **Entry point:** "Teaching →" link in the student rail for staff, and "Back to learning"
   inside (proposed), or a separate app section chosen at login?
2. **Preview:** published version only in the first build (the draft needs per-user model
   selection, a larger change), with the draft as a follow-up?
3. **Phone:** read-only Teacher area as described, or hide it on phones entirely?
4. **Recent activity** on the home screen shows staff names from the audit trail to other
   owners of the same course. OK?
