# Course profiles

One JSON file per course, named `<CODE>.json`. LEA reads these instead of guessing
course-specific behaviour.

| Field | Meaning |
|---|---|
| `code` | Course code, for example `AIML101` |
| `name` | Display name |
| `discipline` | `computing`, `social_science`, `mathematics`, ... (used for reporting) |
| `allows_code` | `true` only if code-based quiz questions make sense for this course |
| `code_language` | Language for code questions when `allows_code` is true, for example `python` |

A course with no profile runs with code questions switched off, and LEA logs a warning.
Only the open course's profile (`AIML101.json`) is committed here (DEMO101's, for the tests, is in `tests/fixtures/data/`); profiles for private courses stay local (see `.gitignore`).

Example for a course without programming:

```json
{
  "code": "STUD101",
  "name": "Study Skills",
  "discipline": "social_science",
  "allows_code": false,
  "code_language": null
}
```
