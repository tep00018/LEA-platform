# Simulation

LEA's second simulation study (v2) runs on the open course AIML101 with simulated
learners whose knowledge is known, so its metrics measure how well LEA grades, tracks
mastery and adapts. It is a new study, separate from the published results.

- Plan, metrics and targets: [`docs/simulation/PLAN.md`](simulation/PLAN.md)
- How to run it, costs and outputs: [`simulation/README.md`](../simulation/README.md)
- Pre-registration (approved before the main run): `simulation/PREREGISTRATION.md`
- The published study's code: [tep00018/LEA](https://github.com/tep00018/LEA), tag `v1.0-snsc`

LEA itself runs unchanged on OpenAI; the simulated students, judges and question bank use
Claude through the researcher's subscription (`claude -p`), never an Anthropic API key.
