# Testing LEA by hand

This is for the tester configuration set up 2026-09-27 (see [STATUS.md](STATUS.md)):
support_off, the V5 grader, and the one-question tutor with broad scope, all as defaults.
No simulation or pilot runs are part of this -- this is for you to actually use LEA.

## 1. Start everything, on your ports

Three processes, in separate terminals, from the repository root unless noted.

**Terminal 1 -- the API**

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8100
```

**Terminal 2 -- the Flutter app** (from `app/`; talks to the API above, so start it second)

```bash
cd app
flutter run -d chrome --web-port 5100 --dart-define=LEA_API_URL=http://127.0.0.1:8100
```

`-d chrome` opens Chrome (or whatever `CHROME_EXECUTABLE` points at; `-d edge` works too).
Use `flutter run -d web-server --web-port 5100 --dart-define=LEA_API_URL=http://127.0.0.1:8100`
instead if you'd rather open the browser yourself at http://localhost:5100.

**Terminal 3 -- Streamlit** (optional; the admin/testing tool, still a real client)

```bash
streamlit run src/ui/streamlit_app.py --server.port 8601
```

The API accepts browser requests from any `localhost` port, so 5100 and 8601 both work
against it with no `.env` change.

## 2. Log in

Register an account in the app (enrol it in `DEMO101`), then mark it as a test account so
your testing never reaches the research logs or analytics:

```bash
python scripts/manage_account.py set-kind <username> test
```

Open http://localhost:5100 and log in with that account.

## 3. Test checklist

Things this round changed or that are worth a deliberate look, not an exhaustive script:

- **Tutor, one question, broad scope.** Start a Tutor session on Week 1. Confirm the
  tutor's messages end on one clear question, stay close to the passage (no invented
  dates/names/numbers), and are reasonably short. Answer normally a few times and confirm
  grading feels right (V5: it should judge only the question actually asked, accept a
  brief-but-complete answer, and not penalize an unrelated aside).
- **A reply the tutor can't check.** Try to get an ungraded, non-warm-up turn -- e.g.
  answer something unrelated to the tutor's question, or answer right after the tutor asks
  something not really checkable. Confirm the chip under your reply says **"Not counted"**,
  not "Warm-up · not counted" (that wording is reserved for the actual first, diagnostic
  reply of a session). Confirm the composer's hint text above the input still reads
  sensibly alongside it.
- **A related-concept question still counts.** If the tutor's question compares the
  current objective with something else you've covered, confirm it's still graded
  (broad scope) rather than left ungraded.
- **Quiz mode.** Run a short quiz on Week 1; confirm multiple-choice/true-false/fill-in
  grade instantly and open-ended grading matches your answer's actual content.
- **Trace your own session.** After testing, run:

  ```bash
  python scripts/session_trace.py <username> DEMO101
  ```

  Confirm it prints one line per turn (tutor and quiz) with a timestamp, the question,
  your reply, graded/correct, cognitive load, ZPD, support level, motivation state, and
  that objective's mastery -- and that it matches what you actually did and saw on screen.
  Add `--week 1` to narrow it to one week.
- **Nothing leaks to research logs.** Since `<username>` is a test account, none of the
  above should add rows to `data/decision_logs/*.csv` or count toward `export_events.py`'s
  research export -- only to the durable event log, tagged `session_kind=test`.

## Notes

- A schema change (a migration, a new Redis key shape) needs the API terminal restarted,
  not just left running -- there's no `--reload` flag above, so this is naturally covered
  by restarting the process.
- `flutter test` runs the full widget-test suite from `app/`; `pytest` from the repository
  root runs the backend suite. Both should be green before you rely on a session trace.
