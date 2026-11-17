# LEA Flutter app: design spec (Chalkboard)

The approved design for the Flutter app. The screenshots in `screens/` are the reference.
`mockup.html` is the interactive mockup they were taken from; open it in a browser to
switch screens, light/dark and desktop/phone, and read its CSS for exact values.

Screenshots are named `<screen>-<frame>-<theme>.png`:
screens `login`, `chat`, `tutor`, `question` (quiz question), `feedback` (quiz feedback),
`results` (quiz results), `progress`; frames `desktop` (1224 px wide) and `phone` (390 px);
themes `light` and `dark`.

## Colour tokens

Use these as the app's `ThemeExtension` (or `ColorScheme` + extension). Never hard-code a
colour in a widget. Light and dark both pass WCAG AA for every text pairing used.

| Token | Light | Dark | Used for |
|---|---|---|---|
| bg | `#F3F5F1` | `#111814` | Page background |
| surface | `#FFFFFF` | `#18221D` | Cards, sidebar, tutor/LEA bubbles, inputs |
| surface-2 | `#E2E9E0` | `#223129` | Selected week, pills, gauge track, option letter chip |
| ink | `#1B2621` | `#E7EFE9` | Main text |
| muted | `#56655D` | `#9DB0A5` | Secondary text, captions, inactive tabs |
| line | `#D2DBD0` | `#2A3B33` | Borders, dividers, meter track |
| primary | `#2E5A47` | `#86C9A8` | Buttons, student bubbles, active tab underline, mastered steps and bars |
| on-primary | `#FFFFFF` | `#0F1F17` | Text on primary |
| accent | `#A98712` | `#F0D35E` | Progress meters, current step, streaming cursor, avatar ring |
| accent-soft | `#F5ECC3` | `#3A3418` | "Week complete" banner (ink text on it) |
| success | `#256B42` | `#74CD99` | "Correct", "Counted · correct" |
| success-soft | `#DDEFE2` | `#1C3A28` | Correct option / mark background |
| warning | `#9A5F06` | `#F0B75A` | Warnings (rare) |
| danger | `#B03A2E` | `#F08D84` | "Incorrect", wrong option, errors |
| danger-soft | `#F7E0DC` | `#3F2220` | Wrong option / feedback background |
| board | `#2E5A47` | `#1C3A2E` | Login panel |
| on-board | `#F3F5F1` | `#E7EFE9` | Text on the login panel |
| chalk | `#F0D35E` | `#F0D35E` | Login underline stroke |

Light-mode `accent` is a darker mustard so meters pass 3:1 against `bg`; keep chalk
yellow (`chalk`) for the login underline only. The theme follows the system setting;
no in-app toggle is needed for the first release.

## Type

- **Display:** Bricolage Grotesque (weights 600–800), for screen titles, the question
  text, big numbers, the LEA wordmark. Letter-spacing −1% on large sizes.
- **Body/UI:** Lexend (300–600), everything else. Lexend was designed for reading ease,
  which suits a study app.
- Bundle both as font assets (don't fetch at runtime), with a system sans fallback.
- Scale (px, desktop / phone): wordmark 22; screen title 24 / 20; question 21 / 18;
  big score 56 / 46; body 14.5; small 13–13.5; captions and labels 11–12 (labels
  uppercase, +8% letter-spacing). Use tabular figures for counts and scores.

## Layout

- **Breakpoint 720 px** (width of the app, not the device).
- **Wide (≥ 720):** left rail 260 px on `surface` with a right border, then the work area.
  Rail, top to bottom: LEA avatar (44 px, 2 px `accent` ring) + "LEA" + tagline "Slide In.
  Study Up. Show Off."; course picker; "Weeks" list (current week on `surface-2` with its
  meter and "2 / 11" count; locked weeks muted with the rule "Opens when 75% of Week 1 is
  mastered"); "Your progress" link; spacer; user row (initial avatar on `primary`, name,
  "Log out"). Work area: mode tabs Chat / Tutor / Quiz (active: `ink`, 600 weight,
  2.5 px `primary` underline), a header band on `bg`, then content.
- **Narrow (< 720):** no rail. Top bar on `surface`: avatar (34 px), mode title, "DEMO101 ·
  Week 1 · Introduction to AI" (ellipsised), and a mastered-count chip ("2 / 11").
  Bottom navigation with four items: Chat, Tutor, Quiz, Progress (icons: speech bubble,
  mortarboard, star, bar chart; active item gets a `surface-2` pill behind the icon).
  The course and week pickers move into a sheet opened from the top bar.
- Side padding 22 px wide / 16 px narrow. Radii: 12 px cards, options, inputs; 9–10 px
  buttons; pills fully rounded. Borders 1 px (`line`); selected elements 1.5 px + 1 px inset.
- Chat bubbles max ~74 characters wide. LEA bubbles: `surface`, 1 px `line`, radius
  4/14/14/14 with LEA's avatar (32 px). Student bubbles: `primary` fill, `on-primary` text,
  radius 14/4/14/14, right-aligned; meta line under them (tag + time).

## Screens and behaviour

API details: `docs/API.md`; spec: `docs/api/openapi.json`.

### Login (`login-*`)
Split screen: the `board` panel (avatar 56 px, "LEA", "Learning Engagement Assistant",
the tagline set large in Bricolage on three lines with a hand-drawn `chalk` underline under
"Study Up.", and a one-line description at the bottom) and the form on `bg`: "Welcome
back", tabs Log in / Create account, fields, full-width primary button, "Forgot your
password? Ask your course tutor to reset it." Narrow: the panel shrinks to a header above
the form (no description).
- Log in: `POST /auth/login`; keep the token in secure storage; on app start, validate it
  with `GET /me` and skip login if valid.
- Create account: username, full name, password, confirm, course picker from
  `GET /courses`; `POST /auth/register`, then switch to Log in with the success message.
- Show API error `detail` under the form. 429: include the wait from `Retry-After`.

### Chat (`chat-*`)
History from `GET /chat/{code}/messages`. Send with `POST /chat/{code}/messages/stream`
and render tokens into a new LEA bubble with the blinking `accent` cursor; on `done`,
replace with the final message. On `error`, remove the pending bubble, keep the student's
text in the input, and show the `detail`. Suggestion chips above the input (three, from
the week's learning-objective titles in the outline) until the first message. Hint under
the input: "Chat doesn't count towards mastery. Use Tutor or Quiz for that."

### Tutor (`tutor-*`)
`GET /tutor` on entry; if none (or it's for another week), show a start panel for the
week ("Ready to learn: Week 1 · Introduction to AI", objective count, "What we'll cover"
list, Start button → `POST /tutor`). Header band: kicker "Objective 3 of 11 · AI Basics",
the objective name as title, the step indicator (one 22×7 px pill per objective, grouped
by learning objective with 10 px gaps; mastered `primary`, current `accent`, others
`line`), and a pill naming the scaffolding ("Step-by-step · medium support"). Replies go
to `POST /tutor/replies/stream`. Under a counted reply, tag "Counted · correct" (success
outline) or "Counted · not yet" (muted); the first reply shows "Warm-up · not counted".
Hint: "Your replies count towards mastery. The first reply is a warm-up and doesn't
count." End button → `POST /tutor/end` → summary sheet. When `completed`, show the
completion state and follow `advanced_to_week`.

### Quiz question (`question-*`)
Header band: "Question 4 of 11 · AI Basics" and "Correct so far 2 / 3", meter below.
Kicker (type · objective), question in Bricolage, options as cards with a letter chip
(A–D); selected: `primary` border + filled chip. True/false: two large cards. Fill in the
blank: one input. Open-ended: textarea with character count (min 10). "Submit answer"
(disabled until answered) and an "End quiz" text link. Code in questions renders in a
monospace block. Nothing is sent until Submit.

### Quiz feedback (`feedback-*`)
Same layout; the chosen option gets `danger-soft` + "Your answer" when wrong, the correct
one `success-soft` + "Correct answer". After answering, `feedback.your_answer` is what was
submitted and `feedback.correct_answer` is the right option letter (multiple choice) or
"True"/"False"; free-text questions have no `correct_answer`, so show the explanation only. Feedback box: "Correct." /
"Not quite." / "Couldn't grade this one" (neutral, not counted) + explanation. "Next
question" → `POST /quiz/next`. Every state has a text label as well as a colour.

### Quiz results (`results-*`)
Banner on `accent-soft` when `advanced_to_week` is set ("Week 1 complete. Week 2 ·
Machine Learning Basics is now open."); big score "8 / 10" of graded answers and a line
explaining any answers not counted; list of every question with objective name and a mark
(Correct / Incorrect / Not counted); buttons "Start Week 2 quiz" (or "Start a new quiz")
and "Review with the tutor". New quiz = `DELETE /quiz` then `POST /quiz`.

### Progress (`progress-*`)
Week cards (current one outlined in `primary`; locked ones say when they open), a legend
(Mastered / In progress / Threshold), then each learning objective with its granular
objectives: name, a gauge (10 px, `surface-2` track, fill `primary` if mastered else
`accent`, a 2 px `ink` tick at the objective's threshold) and "0.74 / 0.65" (keep on one
line). Data: `GET /courses/{code}/progress` and `GET /courses/{code}/mastery?week=N`.

## States every screen needs

- Loading: skeleton blocks in `surface-2`, not spinners over blank screens.
- Empty: chat with no history shows LEA's greeting "Hey, I'm LEA. Got questions on
  DEMO101 Week 1? I'm here to help!" and the suggestion chips.
- Errors: show `detail` from the API (it is written for students). 401 → back to login
  with "Please log in again." 409 `Busy` → "Still working on your last request." 503 →
  inline retry.
- Offline / API down: a banner "Can't reach LEA. Check that the LEA server is running."

## Accessibility

- AA contrast (already met by the tokens); focus rings visible (2 px `primary`, offset 2).
- Colour is never the only signal: correct/incorrect/not counted always have text.
- Semantics labels on icon-only buttons and the step indicator ("Objective 3 of 11,
  2 mastered").
- Respect reduced motion: no blinking cursor, no animated meters.
- Text scales with the system font size up to 200% without clipping.
