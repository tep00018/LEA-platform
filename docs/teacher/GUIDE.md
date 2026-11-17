# LEA for teachers

LEA's Teacher area is where you build a course from your materials, check and publish its
objectives, audit the content, try the course as a student, and see how students are
doing. It is part of the LEA app: open **Teaching** in the left rail (teachers and admins
only). It is made for a desk: on a phone you can look, but not change anything.

LEA suggests; you decide. Nothing LEA drafts, flags or suggests reaches students until you
publish it.

## Contents

1. [Getting an account](#1-getting-an-account)
2. [Create a course](#2-create-a-course)
3. [Upload materials and build](#3-upload-materials-and-build)
4. [Review and publish the objectives](#4-review-and-publish-the-objectives)
5. [Videos for stuck students](#5-videos-for-stuck-students)
6. [Content audit](#6-content-audit)
7. [Try as a student](#7-try-as-a-student)
8. [Analytics](#8-analytics)
9. [For admins: users and owners](#9-for-admins-users-and-owners)
10. [What students notice, and what LEA records](#10-what-students-notice-and-what-lea-records)

## 1. Getting an account

There is no teacher sign-up. An admin creates your account (see section 9) and gives you a
temporary password in person; an admin also makes you an owner of existing courses. You
see only the courses you own.

## 2. Create a course

**Courses → New course.** Give it a code (such as `NN201`), a name, the discipline, the
number of weeks, and whether quizzes may ask code questions (and in which language). The
code is permanent.

Then, in **Setup and materials**, add the **weekly learning objectives**: a title per week
and one objective per line, each a full sentence ("Explain how backpropagation computes
gradients"). LEA uses them to draft the detailed objectives it tracks for each student.

## 3. Upload materials and build

**Upload files** in Setup and materials: PDF, Word, PowerPoint, Excel, Markdown, text and
Jupyter notebooks; MP3, MP4 and WAV recordings (transcribed). Up to 50 MB a file and 1 GB
a course. Choose the week and kind (Lecture, Lab, Reading...) or let LEA go by file type;
LEA renames files to its pattern (`Week03-LectureA-Backprop.pptx`) so students' answers
can cite them.

**Price a build** shows what the build will cost (OpenAI: transcription, image
descriptions, embeddings and the objective draft) before anything is spent; **Start build**
runs it in the background. You can leave the page; progress and each step's log are
kept. **Cancel after this file** stops a build cleanly. Changing materials later? Build
again: deleted files leave the search index too.

A build drafts the objectives; it never publishes them.

**Link a folder of materials** instead of (or alongside) uploading files one at a time: in
the "Linked materials" card, pick a subfolder under your materials folder (it suggests the
one matching your course code) and hit Link. Before you build, check the sync preview --
it lists each file as new, changed, unchanged, removed or rejected (with why), so you can
see what the build will actually pick up. Uploads keep working normally alongside a linked
folder; a linked file shows a "Linked" badge in the materials list. Unlink stops tracking
the folder without deleting anything already built from it.

## 4. Review and publish the objectives

LEA tracks each student's mastery of **granular objectives** (GOs, such as `GO_03_07_002`),
grouped under learning objectives (LOs) and weeks.

- **Objectives** shows the draft from a build, or the live version with **Edit the live
  objectives**. Edit in the table (skill, description, Bloom level, mastery threshold,
  keywords, prerequisites), **Split in two**, **Merge…** or **Remove**; each row shows how
  well the course material supports it ("content match"). **Check now** lists problems
  (a missing prerequisite, a duplicate, a week out of range) before you save.
- Prefer a spreadsheet? **Export to Excel**, edit, and **Import**.
- **Save draft** as you go; students keep the live version meanwhile. **Discard draft**
  drops your edits.
- **Review changes** shows what changes against the live version and how many students are
  affected; **Publish version N** makes it live, with an optional note.

**IDs never change once published.** Renaming or moving an objective keeps its ID; a
removed objective's ID is retired, never reused; splits and merges record where they came
from. When you publish, students' mastery carries over along those links (a split
objective starts from its parent's mastery; a merge takes the mean of its parts), so nobody
loses progress or skips ahead. Every version is kept.

## 5. Videos for stuck students

When a student gets three answers in a row wrong on an objective, the tutor adds a short list
of videos to its reply. It does this **once per stuck streak**, not on every wrong reply after
it; a correct answer or a new objective starts a new streak. **Videos** in the left rail is
where you choose them.

- **Overview.** Every objective with how many of your videos it has, what a stuck student gets
  for it, and **Help shown**: how many students were shown video help in the last 30 days
  (real students only; "< 5" when fewer than 5, and "—" when none). Objectives where students
  are stuck come first, so that is where a few minutes of choosing pay off. Filter by week, or
  show only objectives with or without videos.
- **What a stuck student gets.** *Your videos* if you have chosen any. Otherwise *Automatic
  search*: LEA searches YouTube for the objective (at most once a week, however many students
  ask). When Google's daily quota is used up, or no YouTube key is set, they get *Search
  links*: generic YouTube searches. A banner on the overview says when search is paused.
- **Choose videos for one objective.** Open an objective, paste a YouTube link and, if you
  like, a note ("Watch from 3:20", up to 200 characters), then **Check and add**. LEA checks
  the link with YouTube and fills in the title and channel; a private, removed or
  non-embeddable video is refused with a message saying so. Up to 5 videos per objective.
- **Order.** Students see the **first three**, in your order, with your notes. Use *Move up*
  and *Move down*; a fourth or fifth video waits until one above it is removed. The preview on
  the right shows exactly what a stuck student sees.
- **Remove** takes a video out at once, and *Add it again* (shown for 8 seconds) puts it back
  with its note.

Your videos stay with their objective through later versions of the objectives. Only teachers
who own the course can change them, and every change is recorded. On a phone the screens are
read-only.

## 6. Content audit

**Content audit → Run the audit** checks the live version and lists **findings, not
scores**, most important first, each with its evidence and how far that kind of check has
been validated:

- **Well supported:** accessibility (pictures without alt text, low contrast, slides without
  titles, PDFs without text, recordings without captions) and question writing in your
  reference questions (negative stems, "all of the above", the longest option being
  right).
- **Rule-based:** a prerequisite taught after the objective that needs it.
- **Moderate:** the Bloom balance of each week.
- **Experimental:** objectives the material barely covers, near-duplicate objectives,
  objectives without reference questions. Treat these as hypotheses.
- **Informational:** readability and slide density.

**Accept** what you'll act on, or **Dismiss…** with an optional note ("intended"). Your
decisions are remembered in later runs, which also say what is new and what was resolved.
A run costs well under a cent (only the coverage checks use OpenAI) and shows the cost on
its button.

The question-writing check reads a **reference question bank** if one exists at
`data/course_sources/<CODE>/question_bank.json` -- there's no upload button or script for
this yet; it's a hand-placed JSON file (see AIML101's for the shape). Without one, that
check and "objectives without reference questions" have nothing to check against.

A bank entry marked `tagging.reviewed: true` also gets used by **Quiz mode itself**: a
multiple-choice or true/false question tagged to a given objective is offered to students
verbatim instead of generating a new one, whenever that objective comes up in a quiz. An
auto-tagged bank (e.g. one built alongside the course) defaults every entry to
`reviewed: false`, so review the tags before they reach students -- an unreviewed entry is
never used, only counted by the audit.

## 7. Try as a student

**Try as a student** opens the student app as your own sandbox student (`<you>.preview`),
enrolled in the course, using the live version. A banner reminds you that it's a preview.

- The **Why LEA did this** panel on the right explains each turn: which
  objective, mastery before and after against its threshold, how the answer was graded,
  and the difficulty, scaffolding, motivation and cognitive-load decisions, plus the course
  material it retrieved. Students never see this.
- **Try these** suggests probes for the week ("answer with 'I don't know'", "give a
  wrong answer twice", "ask for the answer outright") to tick off as you go.
- **Reset preview** forgets what the sandbox did; **Back to teaching** returns here.

Nothing the sandbox does counts as student data: it is never in analytics, research data
or exports.

## 8. Analytics

**Analytics** shows how students are doing on each objective, most in need of attention
first. Choose a week and date range; **Real students** is the default.

- **Band:** *Mastered* (most students at the threshold), *Struggling* (many well below it),
  *Developing*, or *Not enough evidence*. A student's level is the mean of their last three
  graded answers.
- **First-try accuracy**, **attempts to master** (graded answers until the last three
  reach the threshold) and the **learning curve** (error rate at the 1st, 2nd, 3rd...
  practice). A falling curve means practice works; a flat or rising one suggests the
  objective or its teaching needs work, or that it mixes two skills.
- **Needs attention** is LEA's heuristic, not a validated measure: low first-try accuracy,
  a flat curve, tutor struggle and chat questions on the topic. It names the factor that
  drove it.
- **Usage** (active students, sessions, time on task) comes last.
- **Export curves (CSV)**: the learning curves, aggregated (no row per student).

Click an objective for its detail: the curve against the course's typical curve, the most
common wrong answers (grouped by objective, because each student's quiz questions are
written fresh), tutor struggle (3+ wrong in a row, video help shown, sessions left while
stuck), what students ask in Chat, and **LEA's suggested action** (edit it or dismiss it;
LEA never acts on it).

- **Group chat questions** sorts the course's chat questions into topics and matches them
  to objectives (GPT-4o mini; the cost is on the button, typically under a cent). It runs
  twice independently and shows how often the two agreed. Questions are sent with names
  removed; topics asked by fewer than 5 students aren't shown.
- **Draft an explainer** writes a short explanation of the objective from your course
  material, for you to edit and use as you like. LEA never publishes it.

**Privacy.** Nothing is shown about fewer than 5 students: those figures read "< 5" or
"Not enough students yet", and there is no per-student view. Test accounts and previews
are never counted.

**Simulated students.** To see the screens with data before a course has students, an admin
can seed simulated students (`docs/SETUP.md`). Choose **Simulated students** to see them;
they are never mixed with real ones.

## 9. For admins: users and owners

**Users and owners** (admins only) lists every account with its role and status. Search
and filter; **Edit** an account to change its role (student, teacher, admin), deactivate
it (signs it out everywhere), mark it a **Test account** (its activity stays out of
research data and analytics), or change its **enrolled courses** -- add one it isn't in
yet, or remove one (their progress in it isn't deleted; re-adding the course later picks
up where they left off). **New teacher account** creates a teacher with a temporary
password: give it to them in person. **Course owners** adds or removes the teachers who
own each course; only teachers and admins can own one.

A student can also do this themselves, from the course picker at the top of the app:
**Add a course…** lists whatever else is open for enrollment, and the **×** beside a course
in the picker leaves it (after confirming) -- their progress stays, so joining it again
later picks up where they left off.

The first admin is made from the command line (`docs/SETUP.md`).

## 10. What students notice, and what LEA records

Students see a course once its objectives are published, and see changes when you publish
a new version. A student who gets stuck on an objective sees the videos you chose for it (section 5). Everything else here (drafts, audits, analytics, previews) is invisible to
them.

LEA logs what teachers do in the Teacher area (edits, publishes, audit decisions, analytics
viewed) for the course's history and for possible research on how teachers use LEA. A
research export replaces teachers' names with pseudonyms, and taking part in a study
needs your separate consent.
