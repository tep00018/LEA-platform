# LEA System Architecture

## Overview

LEA employs a modular, multi-agent architecture that integrates course-specific knowledge, real-time learner assessment, and adaptive content generation to deliver personalized instruction.

## Core Components

### 1. Data Foundation

**Knowledge Component (KC) Model**
- Hierarchical structure: Week → Learning Objective → Granular Objective
- Stores difficulty levels, cognitive taxonomy, mastery thresholds
- Enables targeted skill assessment and adaptive sequencing
- JSON format for programmatic access

**RAG Library (Retrieval-Augmented Generation)**
- Vector database (ChromaDB) storing embedded course content
- Enables semantic search over lectures, labs, and materials
- Provides context-grounded responses to student queries
- Supports multiple document types (PDF, DOCX, videos, code)

### 2. Agentic Environment

**Agent Orchestrator**
- Central coordination layer assessing learner state
- Monitors cognitive load, ZPD alignment, motivation
- Determines scaffolding strategy and content difficulty
- Routes requests to appropriate content generation agents

**Scaffolding Engine**
- Maps learner state to pedagogical interventions
- Four scaffold types: Conceptual, Procedural, Strategic, Metacognitive
- Implements fading logic based on performance trends
- Adjusts support intensity across five levels

**Mastery Tracker**
- Maintains persistent learner progress across sessions
- Tracks mastery at GO, LO, and week levels
- Uses weighted moving averages for stability
- Informs content selection and difficulty adaptation

### 3. Content Generation Agents

**Chat Agent**
- General Q&A using RAG retrieval
- No mastery tracking (chat is ungraded); response style follows cognitive load
- Provides quick answers grounded in course materials
- Remembers the current sitting: the model sees the earlier messages since the last
  30-minute gap, and a short follow-up is searched together with the question before it

**Tutor Agent**
- Guided instruction through the learning objectives the learner still needs: after a quiz,
  only those it got wrong; otherwise those below their mastery threshold. A week that is
  already mastered starts complete and offers a refresher or moving on
- Multi-turn conversations with adaptive scaffolding
- Generates follow-up questions based on understanding
- Provides worked examples when appropriate

**Quiz Agent**
- Dynamic question generation per granular objective
- Multiple question types: MC, T/F, Fill-in-blank, Open-ended
- Difficulty calibration based on learner profile
- Immediate feedback with explanations

### 4. Tool Layer (MCP-style tool registry)

The tool layer follows the Model Context Protocol's tool-calling pattern but runs
in-process: `LEAMCPServer` dispatches to handlers in `MCPToolRegistry` through direct
Python calls. It does not use the MCP SDK or an MCP transport (stdio/SSE).

**Standardized Communication Layer**
- Abstracts tool integration complexity
- Provides one call format for the tools above
- Tools are registered in code (`src/mcp/tool_registry.py`); a list of them is available, but
  nothing discovers or adds tools at run time

**Registered tools**
- RAG retrieval, KC model lookup, mastery summary and update, and YouTube worked examples
  (Tutor only, for a stuck student) are used on student request paths.
- Academic calendar, web search (DuckDuckGo), UK weather and document ingestion are registered
  but nothing calls them on a student request path today.

### 5. Memory Management

**Short-term Memory (Redis)**
- Recent interaction records (24hr TTL), written by Chat and Quiz and queued for consolidation
- Conversation history is not stored here: it lives in the session store (`lea:session:*`)

**Long-term Memory (Redis)**
- Consolidated session summaries (90-day TTL), written by a background worker
- Not read by any mode yet, so it does not personalise anything today. Redesigning it as a
  structured per-objective learner record is on the open list in `docs/STATUS.md`

### 6. Service Layer (`src/services`)

Every client calls the same services; none of them talks to the orchestrator, the
quiz/tutor systems or Redis directly.

| Service | Does |
|---|---|
| `accounts` | register, log in, profile |
| `courses` | course list, week outline, a week's objectives (from the KC model) |
| `progress` | current week and week completion |
| `learning` | the adaptive loop shared by Quiz and Tutor: assess, record, advance week |
| `chat` | answer a question with retrieval; history per learner and course |
| `quiz` | start, answer, next, end; one quiz per learner |
| `tutor` | start, respond, end; one session per learner |

`build_services()` in `src/services/container.py` constructs everything once per
process (one Redis connection pool, one OpenAI client, one retrieval tool).

- **Sessions in Redis.** Quiz, tutor and chat sessions are Pydantic models stored as JSON
  under `lea:session:<kind>:<user>` (chat: `...:<user>:<course>`), with a TTL. A refresh,
  a second tab or a restart of LEA resumes them.
- **Synchronous.** Services are plain blocking calls, safe to run on several threads at
  once. The API (Phase 3) will run each request on a worker thread.
- **Locks.** Short Redis locks guard every read-modify-write of shared learner state:
  `lock:mastery:<user>:<course>`, `lock:motivation:<user>:<course>` (the orchestrator's
  assessment), `lock:progress:<user>:<course>`, and one per stored session. A second
  request on a session that is still busy gets a "still working" error instead of racing.
- **Errors.** Services raise `src.services.errors` exceptions whose messages can be shown
  to the student (`InvalidInput`, `NoActiveSession`, `WrongState`, `Busy`, `Unavailable`).

### 7. HTTP API (`src/api`)

FastAPI over the same services, for the Flutter app (see `docs/API.md`). Endpoints are
plain synchronous functions, so FastAPI runs each request on a worker thread. Login
tokens are validated on the server for every request (only their hashes are stored), and
identity comes only from the token. Chat and tutor replies can be streamed as
server-sent events: the services accept an `on_token` callback, and the API forwards
each piece of text as it arrives. The API and Streamlit can run side by side.

### 8. User Interface (Streamlit)

`src/ui/streamlit_app.py` is a thin client: it draws the pages and keeps only UI state
(who is logged in and the selected course, week and mode). The Flutter app (`app/`, web)
calls the same services through the HTTP API and also has the module-leader screens
(Teacher area and admin), which the Streamlit app does not.

### 9. Module-leader services

Added for the Teacher area (`docs/teacher/GUIDE.md`): `staff` (roles, ownership), `course_setup`
and `jobs` (create a course, upload or link materials, priced background builds), `kc_versions`
(versioned objectives with stable identifiers and mastery carry-over), `audit` (content audit),
`analytics` (learner evidence with small-group suppression), `videos` (curated help videos),
`preview` (try-as-a-student sandbox) and `events` (the pseudonymised event log tagging every
learner event real, test or simulated).

## Data Flow

### Student Interaction Cycle

1. **Input Reception**: User submits query/response
2. **Context Retrieval**: Load conversation history and learner profile
3. **State Assessment**: Calculate cognitive load, ZPD, motivation
4. **Scaffolding Decision**: Determine support type and intensity
5. **Content Generation**: Create adaptive response using RAG + KC model
6. **Mastery Update**: Assess understanding and update progress
7. **Response Delivery**: Present content with appropriate scaffolding
8. **Memory Storage**: Persist interaction for future sessions

## Adaptation as Implemented

Each Quiz answer and Tutor response goes through the same loop:

1. **Before the answer is graded**, the orchestrator reads the learner's recent graded
   evidence (`evidence:<user>:<course>` in Redis) and stored mastery, then computes:
   - accuracy A and ZPD = mean correctness of the last four graded responses (falls
     back to mean GO mastery, then 0.5, for a new learner);
   - cognitive load CL = b0 + b1·G + b2·(1 − A) + b4·Q + b5·T, where G is item difficulty,
     Q this session's interactions and T the task type;
   - the motivation state, from graded streaks, completion, time on task and sentiment;
   - the scaffolding decision from the CL × ZPD matrix, faded one level for every
     `fade_threshold` consecutive correct answers on the current learning objective.
2. **The answer is graded**: exactly for multiple choice and true/false, by the model
   with a JSON verdict for free text. If grading fails the answer is "ungraded" and
   changes nothing.
3. **After grading**, `record_graded_response` appends the evidence and updates GO, LO
   and week mastery through the `mastery_update` tool; week completion is then
   recomputed from the KC model's per-objective thresholds.

Course-specific behaviour comes from `data/course_profiles/<CODE>.json` (for example,
whether code questions are allowed) and the course's KC model, never from defaults
written for another course.

## Scalability Design

**Course-Agnostic Architecture**
- Automated KC model generation from course materials
- Template-based RAG library creation
- Minimal manual configuration per course

**Modular Components**
- Independent agents can be updated without system changes
- Tools are registered in one place (`src/mcp/tool_registry.py`)
- Clear separation of concerns across layers

## Technical Stack

- **Backend**: Python 3.11+
- **LLM**: OpenAI gpt-4o-mini (chat, tutor, quiz, grading, analytics grouping); gpt-4o (course build)
- **Vector DB**: ChromaDB
- **Session Store**: Redis
- **API**: FastAPI + uvicorn
- **UI Framework**: Flutter web (students and module leaders); Streamlit (students)
- **Session models**: Pydantic
- **Embedding Model**: text-embedding-3-small
- **Tool layer**: in-process tool registry modelled on MCP

## Security Considerations

In place: argon2id passwords (old PBKDF2 hashes upgraded at login), hashed server-side
login tokens with idle and absolute expiry, per-username and per-address login limits,
per-user limits on model calls, input length limits, validated course codes and usernames,
and logs that mask keys and passwords. The items below are the broader design goals.

- Environment-based credential management
- User authentication for session isolation
- Redis-backed session management
- No persistent storage of API keys
- Audit logging for instructional decisions

## Future Enhancements

- Multi-LLM support (local models, Claude, etc.)
- Advanced mastery models (Deep Knowledge Tracing)
- Collaborative learning features
- A structured per-objective learner record to replace the unread long-term memory
- Docker containerization for deployment