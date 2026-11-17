# AIML101: sources and attribution

AIML101, "Introduction to AI and Machine Learning (open course)", is LEA's open demo
course. Its lesson text comes from two Microsoft curricula, both under the MIT licence:

| Source | Commit | Date | Licence |
|---|---|---|---|
| [AI for Beginners](https://github.com/microsoft/AI-For-Beginners) | `392d0df1b2647cbee104942390551f1ed9e072c8` | 2026-09-04 | MIT, (c) Microsoft Corporation ([copy](LICENSE-AI-For-Beginners.txt)) |
| [ML for Beginners](https://github.com/microsoft/ML-For-Beginners) | `de2d4e12236445198213a0711855e348e7253cd4` | 2026-09-14 | MIT, (c) Microsoft Corporation ([copy](LICENSE-ML-For-Beginners.txt)) |

The ML for Beginners quiz app, whose English question bank LEA uses as reference
questions, also carries an MIT notice (c) 2020 Arpan Adhikari
([copy](LICENSE-ML-For-Beginners-quiz-app.txt)).

Licences re-checked and sources pinned on 2026-09-25. English text only; no
translations. **No images are included**: the sketchnotes and photos are credited to their
creators, and it is not clear that the MIT licence covers them.

## Files used and changes made

Staged by `data_foundation/stage_aiml101.py` into `data/org_docs/AIML101/`.

| LEA file | Source | Path | Changes |
|---|---|---|---|
| `Week01-LectureA-Introduction-To-AI.md` | Microsoft AI for Beginners | `lessons/1-Intro/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week01-LectureB-History-Of-Machine-Learning.md` | Microsoft ML for Beginners | `1-Introduction/2-history-of-ML/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week01-AssignmentA-AI-Game-Jam.md` | Microsoft AI for Beginners | `lessons/1-Intro/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week01-AssignmentB-History-Timeline.md` | Microsoft ML for Beginners | `1-Introduction/2-history-of-ML/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week02-LectureA-Knowledge-Representation-And-Expert-Systems.md` | Microsoft AI for Beginners | `lessons/2-Symbolic/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week02-LabA-Animal-Expert-System.ipynb` | Microsoft AI for Beginners | `lessons/2-Symbolic/Animals.ipynb` | outputs, execution counts and embedded images removed |
| `Week02-LabB-Family-Ontology.ipynb` | Microsoft AI for Beginners | `lessons/2-Symbolic/FamilyOntology.ipynb` | outputs, execution counts and embedded images removed |
| `Week02-LabC-Concept-Graph.ipynb` | Microsoft AI for Beginners | `lessons/2-Symbolic/MSConceptGraph.ipynb` | outputs, execution counts and embedded images removed |
| `Week02-AssignmentA-Build-An-Ontology.md` | Microsoft AI for Beginners | `lessons/2-Symbolic/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-LectureA-Introduction-To-Machine-Learning.md` | Microsoft ML for Beginners | `1-Introduction/1-intro-to-ML/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-LectureB-Techniques-Of-Machine-Learning.md` | Microsoft ML for Beginners | `1-Introduction/4-techniques-of-ML/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-LectureC-Linear-Regression.md` | Microsoft ML for Beginners | `2-Regression/3-Linear/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-AssignmentA-Get-Up-And-Running.md` | Microsoft ML for Beginners | `1-Introduction/1-intro-to-ML/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-AssignmentB-Interview-A-Data-Scientist.md` | Microsoft ML for Beginners | `1-Introduction/4-techniques-of-ML/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week03-AssignmentC-Regression-Model.md` | Microsoft ML for Beginners | `2-Regression/3-Linear/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week04-LectureA-Introduction-To-Neural-Networks.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week04-LectureB-Perceptron.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/03-Perceptron/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week04-LabA-Perceptron.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/03-Perceptron/Perceptron.ipynb` | outputs, execution counts and embedded images removed |
| `Week04-LabB-Multi-Class-Perceptron.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/03-Perceptron/lab/PerceptronMultiClass.ipynb` | outputs, execution counts and embedded images removed |
| `Week04-AssignmentA-Multi-Class-Perceptron.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/03-Perceptron/lab/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week05-LectureA-Multi-Layered-Perceptron.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/04-OwnFramework/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week05-LabA-Own-Framework.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/04-OwnFramework/OwnFramework.ipynb` | outputs, execution counts and embedded images removed |
| `Week05-LabB-MNIST-With-Own-Framework.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/04-OwnFramework/lab/MyFW_MNIST.ipynb` | outputs, execution counts and embedded images removed |
| `Week05-AssignmentA-MNIST-With-Own-Framework.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/04-OwnFramework/lab/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week05-LectureB-Frameworks-And-Overfitting.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/05-Frameworks/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week05-LabC-Intro-To-PyTorch.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/05-Frameworks/IntroPyTorch.ipynb` | outputs, execution counts and embedded images removed |
| `Week05-LabD-Intro-To-Keras-And-TensorFlow.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/05-Frameworks/IntroKerasTF.ipynb` | outputs, execution counts and embedded images removed |
| `Week05-LabE-Frameworks-Classification.ipynb` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/05-Frameworks/lab/LabFrameworks.ipynb` | outputs, execution counts and embedded images removed |
| `Week05-AssignmentB-Classification-With-Frameworks.md` | Microsoft AI for Beginners | `lessons/3-NeuralNetworks/05-Frameworks/lab/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week06-LectureA-Responsible-AI.md` | Microsoft AI for Beginners | `lessons/7-Ethics/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week06-LectureB-Fairness-In-Machine-Learning.md` | Microsoft ML for Beginners | `1-Introduction/3-fairness/README.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |
| `Week06-AssignmentA-Explore-The-RAI-Toolbox.md` | Microsoft ML for Beginners | `1-Introduction/3-fairness/assignment.md` | images, credits, video thumbnails and quiz links removed; relative links reduced to text; source line added |

## Generated by LEA

These are LEA's own work, derived from the lesson text above (see
`docs/COURSE_CREATION.md`):

- the week structure and the learning objectives (written by the LEA owner from the lessons);
- the knowledge-component model (`data/kc_models/AIML101/`): granular objectives, skill
  names, descriptions, cognitive levels, mastery thresholds, difficulty, prerequisites and
  tags, drafted by OpenAI GPT-4o with `data_foundation/kc_model_generator.py` and reviewed;
- short objective titles, the course profile, document summaries and titles (GPT-4o),
  and the retrieval index (OpenAI embeddings) in `data/md_docs`, `data/metadata` and
  `data/chroma_data`;
- the reference question bank's tags to granular objectives.
