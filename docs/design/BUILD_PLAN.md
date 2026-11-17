# Phase 4 build plan: Flutter app

Build the LEA Flutter client in `app/` against the existing API, matching
`docs/design/DESIGN.md` and the screenshots in `docs/design/screens/`. Web first; the same
code should run on Android and iOS later without layout changes.

## Decisions already made

- **Location:** `app/` in this repo (package name `lea_app`), so the app and the API spec
  change together.
- **Flutter:** current stable. Material 3 with LEA's own theme (tokens in DESIGN.md as a
  `ThemeExtension`), light and dark following the system.
- **State:** `flutter_riverpod`. **Routing:** `go_router` with a redirect to `/login` when
  there's no valid token; routes `/login`, `/chat`, `/tutor`, `/quiz`, `/progress`.
  A responsive shell (rail ≥ 720 px, top bar + bottom nav below) wraps the four modes.
- **API client:** typed models generated from `docs/api/openapi.json` (for example with
  `swagger_parser` + `json_serializable`/`freezed`), or hand-written models kept in step
  with the spec. Base URL from `--dart-define=LEA_API_URL` (default
  `http://127.0.0.1:8100`).
- **Streaming (important):** chat and tutor replies come as server-sent events on a
  **POST** (`/chat/{code}/messages/stream`, `/tutor/replies/stream`), so the browser's
  EventSource can't be used, and `package:http`'s default web client buffers the whole
  response. On web use `package:fetch_client` (Fetch API, real streaming); on mobile the
  default `http` client streams. Parse `event:`/`data:` blocks; events are `token`
  (`{"text"}`), then `done` (same body as the non-streaming endpoint) or `error`
  (`{"detail","code","status"}`). Replace the streamed text with `done`'s message.
- **Token storage:** `flutter_secure_storage`. Send `Authorization: Bearer <token>`.
  On 401 anywhere: clear the token and go to login with "Please log in again."
- **Fonts:** Bricolage Grotesque and Lexend bundled as assets (OFL), not fetched.
- **Errors:** every API error is `{"detail", "code"}`; show `detail`. Honour
  `Retry-After` on 429.

## Milestones (commit after each; keep `flutter analyze` and all tests green)

1. **Foundation.** Create the project, theme (tokens, type scale), fonts, API client,
   auth storage, router, responsive shell with placeholder screens. Widget tests for the
   shell at 1224 px and 390 px. Update root `.gitignore` if needed (Python rules are
   anchored to the root so `app/lib` isn't ignored).
2. **Login and registration** (`login-*.png`). Auto-login from a stored token via `GET /me`.
   Course and week pickers (from `GET /me/courses`, `GET /courses/{code}/outline`,
   current week from `GET /courses/{code}/progress`).
3. **Chat** (`chat-*.png`) with streaming, suggestions and error handling.
4. **Tutor** (`tutor-*.png`): start panel, header band with steps, streamed replies,
   counted/warm-up tags, end summary, week advancement.
5. **Quiz** (`question-*`, `feedback-*`, `results-*`): all four question types,
   feedback with `your_answer`/`correct_answer`, results, new quiz, week advancement.
6. **Progress** (`progress-*.png`) from `/progress` and `/mastery?week=N`.
7. **Polish.** Loading skeletons, empty and error states, offline banner, accessibility
   pass (semantics, focus, text scaling, reduced motion), a web build
   (`flutter build web`) served by the API or any static server, and docs:
   `docs/SETUP.md` (install Flutter, run the app), `CHANGELOG.md` Phase 4 section.

## Definition of done

- Each screen matches its screenshots in light and dark, desktop and phone, closely
  enough that someone comparing them side by side sees the same design.
- A student can register, log in, chat, complete a tutor session and a quiz on DEMO101,
  and see progress, against the local API with real Redis and OpenAI.
- Widget tests for every screen state (using a fake API), a test for the SSE parser
  (tokens split across chunks, `done`, `error`), and all backend tests still pass.
- No secrets in the repo; nothing pushed anywhere unreviewed.

## Backend changes

Keep them small. If the app needs something the API doesn't offer, add it following
the project rules (service → route → docs → spec → tests) and say so in the commit.
