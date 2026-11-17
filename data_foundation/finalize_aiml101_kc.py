"""Finish AIML101's KC model after create_kc_model.py (run from the repository root).

The generator names each learning objective with a short "concept name" from GPT, and
for AIML101 those names came back misaligned (LO_01_02, on top-down and bottom-up AI, was
named "TuringTestIntellect"). The objectives' granular objectives are right; only the
names are wrong, and they also leaked into the GO descriptions and tags. This sets each
objective's title to the approved objective text, adds a short title, and replaces
the wrong name wherever it appears, in both week_navigation and quick_lookup.

    python data_foundation/finalize_aiml101_kc.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "kc_models" / "AIML101" / "kc_model_AIML101.json"

# lo_id -> (approved objective, short title). Approved by the owner, 2026-09-25.
OBJECTIVES = {
    "LO_01_01": ("Distinguish weak (narrow) AI from strong (general) AI, and explain how the Turing test defines intelligence", "Weak and Strong AI"),
    "LO_01_02": ("Compare the top-down (symbolic) and bottom-up (neural) approaches to AI", "Top-Down and Bottom-Up AI"),
    "LO_01_03": ("Describe the main periods in the history of AI and machine learning, including the AI winters and the rise of deep learning", "History of AI"),
    "LO_02_04": ("Explain knowledge representation and classify the main kinds (semantic networks, frames, rules and logic)", "Knowledge Representation"),
    "LO_02_05": ("Describe how an expert system uses a knowledge base and an inference engine, with forward and backward chaining", "Expert Systems"),
    "LO_02_06": ("Explain ontologies, the semantic web and concept graphs", "Ontologies and the Semantic Web"),
    "LO_03_07": ("Define machine learning and distinguish it from AI and deep learning", "What Machine Learning Is"),
    "LO_03_08": ("Describe the steps of building a machine learning model: the question, data, features and target, train/test split, training, evaluation and tuning", "Building an ML Model"),
    "LO_03_09": ("Explain linear regression, correlation, and how the error of a regression model is measured", "Linear Regression"),
    "LO_04_10": ("Describe the model of an artificial neuron and the perceptron", "Neurons and the Perceptron"),
    "LO_04_11": ("Explain how the perceptron learning rule trains a binary classifier, and its limit to linearly separable data", "Training a Perceptron"),
    "LO_05_12": ("Explain learning as minimising a loss function with gradient descent", "Loss and Gradient Descent"),
    "LO_05_13": ("Describe multi-layer perceptrons and backpropagation", "Multi-Layer Perceptrons"),
    "LO_05_14": ("Describe what neural network frameworks such as PyTorch and Keras provide", "Neural Network Frameworks"),
    "LO_05_15": ("Explain overfitting, how to detect and prevent it, and the bias-variance trade-off", "Overfitting"),
    "LO_06_16": ("Describe the principles of responsible AI: fairness, reliability and safety, privacy and security, inclusiveness, transparency and accountability", "Responsible AI Principles"),
    "LO_06_17": ("Explain how unfairness arises in machine learning systems, and the tools for detecting and reducing it", "Fairness in ML"),
}


def fix_go(go: dict, wrong: str, right: str) -> None:
    pattern = re.compile(re.escape(wrong), re.IGNORECASE)
    go["description"] = pattern.sub(right.lower(), go.get("description", ""))
    go["conceptual_tags"] = [right.lower() if t.lower() == wrong.lower() else t for t in go.get("conceptual_tags", [])]


def fix_lo(lo: dict, wrong_names: dict) -> None:
    title, short = OBJECTIVES[lo["lo_id"]]
    wrong = wrong_names[lo["lo_id"]]
    lo["title"], lo["short_title"] = title, short
    if "conceptual_tags" in lo:
        lo["conceptual_tags"] = [short.lower() if t.lower() == wrong.lower() else t for t in lo["conceptual_tags"]]
    for go in lo.get("granular_objectives", []):
        fix_go(go, wrong, short)


def main() -> None:
    model = json.loads(PATH.read_text(encoding="utf-8"))
    los = [lo for week in model["week_navigation"].values() for lo in week["learning_objectives"]]
    assert {lo["lo_id"] for lo in los} == set(OBJECTIVES), "objective IDs don't match the approved list"
    wrong_names = {lo["lo_id"]: lo["title"] for lo in los}
    if all(lo["title"] == OBJECTIVES[lo["lo_id"]][0] for lo in los):
        print("Already finalised.")
        return
    for lo in los:
        fix_lo(lo, wrong_names)
    lookup = model["quick_lookup"]
    for lo_id, lo in lookup["lo_by_id"].items():
        fix_lo(lo, wrong_names)
    for go in lookup["go_by_id"].values():
        lo_id = go["parent_lo_id"]
        fix_go(go, wrong_names[lo_id], OBJECTIVES[lo_id][1])
    PATH.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Finalised {len(los)} objectives in {PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
