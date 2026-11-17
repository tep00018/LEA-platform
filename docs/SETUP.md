# LEA Setup Guide

## Requirements

- Python 3.10 or later (3.11 recommended)
- Redis: local, Docker, or Redis Cloud
- An OpenAI API key
- About 8 GB of disk for the Python environment (PyTorch is the largest part)

## 1. Get the code

```bash
git clone <your repo URL> LEA
cd LEA
```

## 2. Create an environment

Either a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

or a conda environment:

```bash
conda create -n lea python=3.11
conda activate lea
```

## 3. Install dependencies

`requirements.txt` is a lock file with the exact versions LEA is tested against.

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e . --no-deps
```

To save about 2 GB, install the CPU-only build of PyTorch first (LEA only uses it
for the small reranking model):

```bash
pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
```

Optional extras:

```bash
pip install -e ".[ingest]"   # course onboarding pipeline (also needs ffmpeg on PATH)
pip install -e ".[eval]"     # RAGAS evaluation scripts
pip install -r requirements-dev.txt   # tests and linting
```

## 4. Redis

Any of these works. Set `REDIS_URL` to match.

- **Redis Cloud:** `REDIS_URL=redis://default:<password>@<host>:<port>`
- **Docker:** `docker run -d -p 6379:6379 redis:7` then `REDIS_URL=redis://localhost:6379`
- **macOS:** `brew install redis && brew services start redis`
- **Ubuntu/Debian:** `sudo apt-get install redis-server`

### Keeping a free Redis Cloud database alive

Free Redis Cloud databases can be deleted after a period of inactivity. Run the keepalive
script weekly (the script's header shows a Windows Task Scheduler command):

```bash
python scripts/redis_keepalive.py
```

### Running Redis on this PC instead (Windows)

If LEA runs on one PC, a local Redis avoids the cloud expiry entirely. Two options:

- **Memurai Developer** (a Redis-compatible Windows service on port 6379):
  `winget install Memurai.MemuraiDeveloper`, then `REDIS_URL=redis://localhost:6379`.
  Check the developer edition's usage terms on memurai.com.
- **Docker Desktop:** `docker run -d --name lea-redis -p 6379:6379 --restart unless-stopped redis:7 redis-server --save 60 1`,
  then `REDIS_URL=redis://localhost:6379`. `--save 60 1` writes data to disk so it survives restarts.

## 5. Configure

```bash
cp .env.example .env
```

Fill in `OPENAI_API_KEY` and `REDIS_URL`. `YOUTUBE_API_KEY` is optional.
Set `LOG_LEVEL=DEBUG` to see the detailed trace of every orchestrator step.

`LEA_COURSE_MATERIALS_ROOT` (optional; default `~/Documents/LEA/course_materials`)
is where a course's **linked materials** folders live, one subfolder per course code,
outside the repo -- see docs/API.md's "Linked materials sources" and the Teacher Guide's
"Upload materials and build" section.

Set `LEA_EVENT_SALT` to a long random secret, once:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

It pseudonymises learners in the event log. Never change it and back it up with `.env`:
if it is lost, new events can't be linked to a learner's earlier ones. Without it the
event log is off (LEA still runs and says so in its log).

### The first admin

Teachers and admins use the Teacher area of the Flutter app. There is no self-service
teacher sign-up: register an account in the app as usual, then make it an admin:

```bash
python scripts/manage_account.py make-admin alice
```

From then on, admins create teacher accounts and assign courses to them in the app (or
with the `/admin` API).

### The event log

Every quiz, tutor and chat event, and every adaptive decision, is appended to
`data/lea_events.db` (SQLite; gitignored). Redis keeps only each learner's recent
evidence, so this file is the only full history: **back it up** by copying it while LEA
is stopped, or at any time with

```bash
python -c "import sqlite3; sqlite3.connect('data/lea_events.db').backup(sqlite3.connect('backup.db'))"
```

Learners appear only as pseudonyms. Chat questions and answers are kept with the student's
own username and name removed, which is not full anonymisation: treat the file as personal
data.

Mark test accounts so their activity is tagged `test` and left out of research logs and
exports, and record research consent:

```bash
python scripts/manage_account.py set-kind alice test     # real (default), test or simulated
python scripts/manage_account.py consent alice yes       # yes, no or unset
python scripts/export_events.py research.csv             # consented, real learners only
```

### Teacher-area files and what to back up

Besides `.env` and `data/lea_events.db`, the Teacher area keeps its state in these files (all
gitignored except the open course AIML101's published objectives):

| Where | What |
|---|---|
| `data/course_profiles/<CODE>.json` | Each course's profile (written by its onboarding job) |
| `data/course_uploads/<CODE>/` | Uploaded materials, as uploaded |
| `data/org_docs/<CODE>/`, `data/chroma_data/` | Staged materials and their search index (rebuilt by an onboarding job) |
| `data/kc_models/<CODE>/` | The live objectives, every published version (`versions/v1.json`...), the ID ledger and any draft |
| `data/audits/<CODE>/` | Content audit runs and decisions |
| `data/course_videos/<CODE>.json` | The videos instructors chose for stuck students, by objective |
| `data/analytics/<CODE>/` | Chat-topic groupings |
| `LEA_COURSE_MATERIALS_ROOT` (outside `data/`, not gitignored by this repo since it isn't inside it) | Linked materials folders -- back these up separately; a course only *records the link* (in its profile), the files themselves live entirely in this folder |

Users, roles, the courses created in the app, their owners and weekly objectives, jobs and
mastery are in Redis, not in `data`. Back up the `data` folder and
`.env` together, with LEA stopped (or copy `lea_events.db` with the command above).
`data/kc_models/<CODE>/versions/` matters most after the event log: published GO IDs are
never reused, and the ledger there is what guarantees it.

### Simulated students and teaching-study exports

To see the analytics screens with data before any student has used a course, seed
simulated students. They are tagged `simulated`: never counted as real, never in a
research export, and shown only when "Simulated students" is chosen:

```bash
python scripts/seed_simulated.py AIML101                  # 30 students, every week
python scripts/seed_simulated.py AIML101 --students 12 --weeks 3 --again
```

Teacher and admin actions (KC review, audit decisions, analytics views, previews) are
logged too. For a study of how teachers use LEA, export them with every teacher
pseudonymised; LEA doesn't record teacher consent, so get it separately:

```bash
python scripts/export_events.py teaching.csv --teachers
```

## 6. Run

From the repository root:

```bash
streamlit run src/ui/streamlit_app.py
```

Open http://localhost:8600 (set in `.streamlit/config.toml`). Use `--server.port 8601` if 8600 is taken.

### The API (for the Flutter app)

```bash
uvicorn src.api.main:app --host 127.0.0.1 --port 8100
```

See [API.md](API.md) for authentication, endpoints and running it on your network.

### The Flutter app (web)

The app lives in `app/`. It talks to the API above, so start the API first.

**Install.** Install Flutter from https://docs.flutter.dev/get-started/install (stable
channel) and put it on your PATH. `flutter doctor` should show Flutter and a browser; the
Android and Visual Studio lines don't matter for the web app.

**Run while developing.** From `app/`:

```bash
flutter pub get
flutter run -d chrome --web-port 5100 --dart-define=LEA_API_URL=http://127.0.0.1:8100
```

`-d chrome` opens Chrome, or whatever browser `CHROME_EXECUTABLE` points at (Edge works);
without either, use `-d edge`. `flutter run -d web-server --web-port 5100 ...` serves the
app without opening a browser. `LEA_API_URL` defaults to `http://127.0.0.1:8100`.

**Check.** `flutter analyze` and `flutter test` (widget tests against a fake API, no
server needed). To compare screens with the design, `flutter test
tool/render_screens_test.dart` renders them with the real fonts into `app/build/screens/`,
named like `docs/design/screens/`.

**Build and serve.** The build is plain static files, so any web server can host it:

```bash
flutter build web --release --dart-define=LEA_API_URL=http://127.0.0.1:8100
python -m http.server 5101 --bind 127.0.0.1 --directory build/web
```

Open http://localhost:5101. `LEA_API_URL` is fixed at build time: build again with the
address students will reach the API on (for example `https://lea.example.org/api`). The
API accepts browser requests from any `localhost` port; for any other address the app is
served from, add it to `LEA_CORS_ORIGINS` in `.env` (see [API.md](API.md)).

### Sharing outside your network (optional)

```bash
ngrok config add-authtoken <YOUR_TOKEN>   # once
ngrok http 8600
```

## Tests and linting

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

The tests run against an in-process Redis (fakeredis) and never call OpenAI, so no
credentials are needed.

## Troubleshooting

- **Redis connection errors:** check `REDIS_URL`; for a local server, `redis-cli ping` should return `PONG`.
- **"LEA can't start until these settings are fixed":** the page lists exactly which setting is missing or wrong. Fix `.env` and restart LEA.
- **ChromaDB errors for AIML101:** the committed store needs `chromadb==0.6.3`, which the lock file pins.
- **`git status` shows `data/chroma_data/AIML101/.../length.bin` modified:** ChromaDB rewrites
  its index file when it is searched. It's harmless; run `git checkout -- data/chroma_data`
  before pulling updates if git complains.

## Adding courses

See the [Course Creation Guide](COURSE_CREATION.md).
