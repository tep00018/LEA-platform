# LEA: Learning Engagement Assistant

An adaptive, scalable, tri-modal AI tutoring system designed to personalize instruction in STEM education.

## Overview

LEA (Learning Engagement Assistant) is a proof-of-concept agentic AI system that provides personalized academic support through three learning modes:

- **Chat Mode**: Open-ended Q&A with course-grounded responses
- **Tutor Mode**: Guided instruction with adaptive scaffolding
- **Quiz Mode**: Dynamic assessment with difficulty calibration

## Key Features

- **Adaptive Scaffolding**: Real-time adjustment based on cognitive load and learner performance
- **Knowledge Component Modeling**: Hierarchical learning objectives with mastery tracking
- **RAG-Based Content**: Retrieval-Augmented Generation grounded in course materials
- **Multi-Modal Learning**: Flexible interaction styles for diverse learner needs
- **Scalable Architecture**: Supports multiple courses with automated content generation

## Status

This is the development version of LEA, building on the system described in the published
papers. The code accompanying the SN Computer Science article is in
https://github.com/tep00018/LEA (tag `v1.0-snsc`).

## What's in this version

- A FastAPI backend and HTTP API over a service layer (`src/services/`, `src/api/`)
- A Flutter client, web first (`app/`)
- A Teacher area: course onboarding as background jobs, knowledge-component versions with
  review and publishing, content audit, student analytics and try-as-student preview
- The open course AIML101
- A durable event log that tags real, test and simulated learners
- Chat with conversation memory
- Reference question banks in Quiz mode
- Instructor-curated YouTube help in Tutor mode
- The Simulation v2 harness (`simulation/`)

## Data availability

Institutional course materials, knowledge-component models, vector stores and evaluation
data for real courses are not released. The one course included here, **AIML101**, is an
open course built from MIT-licensed material. A small synthetic course (DEMO101) is used
by the tests.

## Demo Course

Includes **AIML101, Introduction to AI and Machine Learning (open course)**, built from
Microsoft's MIT-licensed *AI for Beginners* and *ML for Beginners*
(see `data/course_sources/AIML101/ATTRIBUTION.md`):
- 6 weeks: introduction and history of AI, symbolic AI, machine learning basics, the
  perceptron, multi-layer networks and overfitting, ethics and fairness
- 17 learning objectives and 63 granular objectives
- a ready retrieval library (32 lesson files) and a 67-question reference question bank

The synthetic course DEMO101 lives in `tests/fixtures/data/` for the tests.

## Quick Start

### Prerequisites

- Python 3.10+ (3.11 recommended)
- Redis (local, Docker or Redis Cloud)
- OpenAI API key

### Installation

```bash
git clone https://github.com/tep00018/LEA-platform.git
cd LEA-platform

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
pip install -e . --no-deps

cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
# Edit .env with your credentials
```

### Running LEA

```bash
# Start Redis (skip if you use Redis Cloud)
redis-server

# Run the application from the repository root
streamlit run src/ui/streamlit_app.py
```

Visit http://localhost:8600 (the port is set in `.streamlit/config.toml`).

The Flutter app (web) in `app/` is the new front end; see
[docs/SETUP.md](docs/SETUP.md#the-flutter-app-web) to run or build it.

The HTTP API (for the Flutter app) runs separately:
`uvicorn src.api.main:app --port 8100`. See [docs/API.md](docs/API.md).

## Documentation

- [Setup Guide](docs/SETUP.md) - Installation instructions
- [Architecture](docs/ARCHITECTURE.md) - System design
- [API](docs/API.md) - HTTP API for the Flutter app
- [Course Creation](docs/COURSE_CREATION.md) - Adding new courses
- [Teacher guide](docs/teacher/GUIDE.md) - The Teacher area: courses, objectives, audit, preview, analytics
- [Simulation](docs/SIMULATION.md) - Simulation v2 on AIML101 (ground-truth learners)

## Development

```bash
pip install -r requirements-dev.txt
pytest          # runs without OpenAI credentials, against an in-process Redis
ruff check .
```

See [CHANGELOG.md](CHANGELOG.md) for what has changed and what is still open.

## Research Context

Developed as part of a research programme on adaptive intelligent tutoring systems.

## License

Apache 2.0 License - see [LICENSE.txt](LICENSE.txt)

## Citation

Conference paper: *Learning Engagement Assistant (LEA): A Multi-Agent AI Framework for
Adaptive and Personalized Learning with Simulated Student Agents*, ICAART 2026,
DOI [10.5220/0014418900004052](https://doi.org/10.5220/0014418900004052).

Journal article (under review): *Learning Engagement Assistant (LEA): Cross-Course Scalability and Classroom Evaluation of an Agentic AI Tutoring System*, SN Computer Science. (To be updated with volume, pages and DOI once published.)

Dissertation:

```bibtex
@mastersthesis{rumble2025,
  title={LEA: An Adaptive Agentic AI Framework for Personalized STEM Education},
  author={Rumble, Teri},
  year={2025},
  school={Abertay University}
}
```