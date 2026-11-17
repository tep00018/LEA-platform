# Course Creation Guide

This guide explains how to add a new course to LEA.

## Overview

Adding a course requires four main steps:
1. Prepare course materials
2. Generate Knowledge Component (KC) model
3. Build RAG library
4. Write the course profile

## Prerequisites

- Course materials (PDFs, DOCX, videos, code, etc.)
- OpenAI API key configured in `.env`
- Redis running

## Step 1: Organize Course Materials

### Create Directory Structure

```bash
cd LEA
mkdir -p data/org_docs/YOUR_COURSE_CODE
mkdir -p data/kc_models/YOUR_COURSE_CODE
```

### File Naming Convention

Use this format for all materials:
```
Week{N}-{Type}{Letter}-{Description}.{ext}
```

Examples:
- `Week1-LectureA-Introduction.pdf`
- `Week2-LabA-PythonBasics.ipynb`
- `Week3-VideoA-DeepLearning.mp4`
- `Week5-TutorialB-Optimization.docx`

### Supported File Types

- **Documents**: PDF, DOCX, TXT, Markdown (.md, used as it is)
- **Notebooks**: .ipynb
- **Videos**: .mp4, .avi, .mov, .mkv by this command-line route (needs `pip install -e ".[ingest]"` and ffmpeg). The
  Teacher area's upload accepts only .mp3, .mp4 and .wav, and rejects other types
- **Presentations**: .pptx

Place all files in `data/org_docs/YOUR_COURSE_CODE/`

## Step 2: Create KC Model Template

### Create Excel Template

Create `data_foundation/YOUR_COURSE_CODE.xlsx` with two sheets:

**Sheet 1: Template**

| Week | Week Description | Learning Objectives | Supporting Materials |
|------|------------------|---------------------|---------------------|
| 1 | Introduction | 1. Objective one<br>2. Objective two | data/md_docs/YOUR_COURSE_CODE/Week1- |
| 2 | Core Concepts | 1. Objective three<br>2. Objective four | data/md_docs/YOUR_COURSE_CODE/Week2- |

**Sheet 2: Partial_Example**

Copy the structure from `DEMO101.xlsx` Partial_Example sheet or use this minimal example:

| KC# | Module | Module Name | Week # | Week Name | LO# | Learning Objective Name | GO# | Granular Objective Name | cognitive_level |
|-----|--------|-------------|---------|-----------|-----|-------------------------|-----|-------------------------|-----------------|
| KC_W01_L01_001 | YOUR_CODE | Course Name | W01 | Week 1 | L01 | LO Name | 001 | GO Name | Knowledge |

### Generate KC Model

```bash
cd data_foundation
python kc_model_generator.py YOUR_COURSE_CODE
```

This creates:
- `YOUR_COURSE_CODE_Improved_KC_Model.xlsx`

### Review and Edit

1. Open the generated Excel file
2. Review granular objectives for accuracy
3. Adjust cognitive levels and difficulty if needed
4. Save as `YOUR_COURSE_CODE_Improved_KC_Model_Updated.xlsx`

Learning objectives written as full sentences ("Describe the scope and structure of ...")
are what LEA's prompts should see, but they are long for the app. After converting to
JSON (below), give each objective a `short_title` of two to five words in
`data/kc_models/YOUR_COURSE_CODE/kc_model_YOUR_COURSE_CODE.json`; the app shows it
wherever an objective is named. The generator's own `short_title` is just the first 50
characters plus "...", which the app ignores in favour of the full title.

### Convert to JSON

```bash
python create_kc_model.py YOUR_COURSE_CODE
```

This writes `KC_Model_YOUR_COURSE_CODE.json` and `KC_Model_YOUR_COURSE_CODE_ui_navigation.json`
in `data_foundation/`, and installs the navigation file where LEA loads it:
- `data/kc_models/YOUR_COURSE_CODE/kc_model_YOUR_COURSE_CODE.json`

## Step 3: Generate RAG Library

### Process Course Materials

```bash
cd ..
python data_foundation/rag_library_creation.py YOUR_COURSE_CODE
```

This will:
1. Convert all files to markdown
2. Extract text from PDFs, videos, etc.
3. Chunk content into semantic segments
4. Generate embeddings
5. Store in ChromaDB

Output:
- `data/md_docs/YOUR_COURSE_CODE/` - Markdown conversions
- `data/chroma_data/YOUR_COURSE_CODE/` - Vector database

### Clean lecture transcripts (optional, recommended)

Speech-to-text transcripts mishear names ("Ackinson Schiffrin"), have no paragraphs and
carry recording chatter. Before building the library, you can clean them:

```bash
python data_foundation/clean_transcripts.py YOUR_COURSE_CODE --all
```

It edits each `*Transcript*.txt` in `data/org_docs/YOUR_COURSE_CODE/` with GPT-4o in
600-word pieces, using a glossary from the KC model and the slides' citations, and writes
the results and a `report.json` to `data/metadata/clean_transcripts/YOUR_COURSE_CODE/`.
Review anything flagged (a big drop in length, a name that disappeared, `[unclear]`), then
copy the approved files over the originals and run `rag_library_creation.py` again: only
changed files are re-embedded, and their old chunks are replaced. Budget about $0.02 per
1,000 words. A transcript that is gibberish throughout (a failed transcription) should be
removed rather than cleaned.

### Verify RAG Library

```bash
python data_foundation/verify_rag_content.py YOUR_COURSE_CODE
python data_foundation/verify_rag_content.py YOUR_COURSE_CODE --query "a question from week 1"
```

It prints the chunk count and source files, then runs the queries through the same
retrieval LEA uses. It exits with an error if the store is missing or empty.

## Step 3b: Write the Course Profile

Create `data/course_profiles/YOUR_COURSE_CODE.json`. It tells LEA the facts it must not
guess, most importantly whether code questions make sense:

```json
{
  "code": "YOUR_COURSE_CODE",
  "name": "Course Name",
  "discipline": "social_science",
  "allows_code": false,
  "code_language": null
}
```

Without a profile LEA still runs, but code questions are off and a warning is logged.
See `data/course_profiles/README.md` for the fields.

## Step 4: Test the Course

### Start LEA

```bash
streamlit run src/ui/streamlit_app.py
```

### Test Each Mode

1. **Register/Login** with a test account
2. **Select** your new course from the dropdown
3. **Chat Mode**: Ask a general question about Week 1 content
4. **Tutor Mode**: Start tutoring on Week 1, LO 1
5. **Quiz Mode**: Take a quiz on Week 1

### Troubleshooting

**KC Model Not Loading**
```bash
ls data/kc_models/YOUR_COURSE_CODE/
# Should show kc_model_YOUR_COURSE_CODE.json
```

**RAG Retrieval Empty**
```bash
python data_foundation/verify_rag_content.py YOUR_COURSE_CODE
# Should show document count > 0
```

**Missing Course in Dropdown**
- Verify JSON file exists in correct location
- Check file naming matches course code
- Restart Streamlit

## In the Teacher area (API)

Teachers can do Steps 1-3 without touching files or scripts: create the course, enter the
weekly objectives, upload materials and run an onboarding job, which shows its OpenAI cost
before it starts. The job drafts the KC model; the teacher reviews it (in a table or as a
spreadsheet) and publishes it. See "Course onboarding" and "KC review and versions" in
`docs/API.md`. Once a course has versions, edit its model through the Teacher area, not by
hand: IDs, lineage and students' mastery depend on it. Courses onboarded by hand keep their files as they
are; the Teacher area doesn't manage their uploads.

## Reference question banks

A course can ship human-written questions as a reference bank in
`data/course_sources/<CODE>/question_bank.json`. It feeds the content audit and serves as
examples for question writing. **Quiz mode uses entries marked `"reviewed": true`** in a
multiple-choice or true/false question for the matching objective, served as written with no
model call; unreviewed entries are only counted by the audit. A new bank has every entry
unreviewed, so review the tagging before it reaches students.

```json
{
  "course": "AIML101",
  "format": "lea-reference-question-bank/1",
  "note": "...",
  "questions": [
    {
      "id": "AI4B-101-1",
      "week": 1,
      "type": "multiple_choice",
      "text": "A famous 19th century proto-computer engineer was",
      "options": ["Charles Barkley", "Charles Babbage", "Charles Darwin"],
      "correct_index": 1,
      "go_id": "GO_01_03_001",
      "lo_id": "LO_01_03",
      "tagging": {"method": "embedding similarity ...", "score": 0.22, "reviewed": false},
      "source": {"curriculum": "AI for Beginners", "file": "...", "quiz_id": 101, "quiz_title": "...", "kind": "pre"}
    }
  ]
}
```

`type` is `multiple_choice` or `true_false`; `correct_index` points into `options`. GO tags
are suggestions until a teacher reviews them.

## The open course (AIML101)

AIML101 is built from Microsoft's MIT-licensed *AI for Beginners* and *ML for Beginners*
(sources, commits and changes in `data/course_sources/AIML101/ATTRIBUTION.md`). To rebuild
it from the pinned commits:

```bash
git clone https://github.com/microsoft/AI-For-Beginners ../sources/AI-For-Beginners   # then check out the commit
git clone https://github.com/microsoft/ML-For-Beginners ../sources/ML-For-Beginners   # in ATTRIBUTION.md
python data_foundation/stage_aiml101.py ../sources
python data_foundation/rag_library_creation.py AIML101
cd data_foundation
python kc_model_generator.py AIML101 --model gpt-4o      # then review into AIML101_Improved_KC_Model_Updated.xlsx
python create_kc_model.py AIML101
cd ..
python data_foundation/finalize_aiml101_kc.py            # approved objective titles and short titles
python data_foundation/build_aiml101_question_bank.py ../sources
```

The committed `AIML101_Improved_KC_Model_Updated.xlsx` is the reviewed model: the reviewer removed
five duplicate granular objectives and capped mastery thresholds at 0.85.

## Best Practices

### Learning Objectives

- Be specific and measurable
- Use action verbs (understand, apply, analyze)
- Align with Bloom's taxonomy
- Limit to 3-5 per week

### Course Materials

- Include varied content types
- Provide worked examples
- Include code samples when relevant
- Keep files reasonably sized (<50MB each)

### KC Model Review

- Verify cognitive levels are appropriate
- Check mastery thresholds (the Teacher area accepts 0.5 to 0.95; 0.6 to 0.9 is the usual range)
- Ensure granular objectives are distinct
- Validate prerequisite relationships

## Advanced Configuration

### Custom Course Names

Edit `data_foundation/kc_model_generator.py`:

```python
course_names = {
    "AIML101": "Introduction to AI and Machine Learning",
    "YOUR_CODE": "Your Course Name",
}
```

### Adjust Mastery Thresholds

Edit generated KC model JSON:
```json
{
  "mastery_threshold": 0.75,  // Adjust per objective
  "difficulty": 3              // 1-5 scale
}
```

### Custom Scaffolding Rules

Modify `src/core/scaffolding_engine.py` for course-specific logic.

## Example: Adding a new course (NEW101)

```bash
# 1. Create directories
mkdir -p data/org_docs/NEW101

# 2. Add course files
# (Copy PDFs, etc. to data/org_docs/NEW101/)

# 3. Create template
# (Create NEW101.xlsx in data_foundation/)

# 4. Generate KC model
cd data_foundation
python kc_model_generator.py NEW101
# Review NEW101_Improved_KC_Model.xlsx
python create_kc_model.py NEW101

# 5. Generate RAG
cd ..
python data_foundation/rag_library_creation.py NEW101

# 6. Test
streamlit run src/ui/streamlit_app.py
```

## Need Help?

- Check the open course (AIML101) as an example
- Review error logs in console output
- Verify file permissions and paths
- Ensure OpenAI API key has credits