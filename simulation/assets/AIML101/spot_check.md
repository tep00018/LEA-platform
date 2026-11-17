# AIML101 question bank: spot check

Generated 2026-09-25T22:41:00+00:00 with claude-sonnet-5. For each entry, tick what holds and note anything wrong.

## 1. GO_01_01_001 (week 1): Define Weak Ai

1. what does weak AI actually mean?
2. is Siri or Alexa weak AI? why
3. can you give me another example of that? (follow-up to 2)

**Reference answer:** Weak AI refers to AI systems designed and trained for a specific task or a narrow set of tasks. They do well at that predefined job but lack true understanding or consciousness. Examples include virtual assistants like Siri or Alexa and recommendation algorithms used by streaming services.

**Source:** `Week01-LectureA-Introduction-To-AI.md`: "Weak AI refers to AI systems that are designed and trained for a specific task or a narrow set of tasks."

**Misconceptions:**
- Weak AI is a system designed to solve many tasks. (quiz distractor)
- Weak AI just means an AI that is badly built or performs poorly at its job. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 2. GO_01_02_002 (week 1): Neural Network Basics

1. how do neural networks work in AI, basically?
2. why is the bottom-up approach compared to how a baby learns?
3. what do you mean by training data there? (follow-up to 1)

**Reference answer:** The bottom-up approach models the structure of the human brain, which is made of a huge number of simple units called neurons. Each artificial neuron acts like a weighted average of its inputs. A network of neurons is trained to solve useful problems by giving it training data, or examples.

**Source:** `Week01-LectureA-Introduction-To-AI.md`: "Each neuron acts like a weighted average of its inputs, and we can train a network of neurons to solve useful problems by providing training data."

**Misconceptions:**
- A bottom-up approach to AI is not based on neural networks. (quiz distractor)
- Neural networks are programmed with explicit if-then rules written by experts. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 3. GO_01_03_001 (week 1): Identify Ai Historical Periods

1. what are the main periods in the history of AI?
2. when was the term artificial intelligence coined and where?
3. what happened in the golden years? (follow-up to 1)

**Reference answer:** AI as a field began to crystallize in the 1950s. The term 'artificial intelligence' was coined at the 1956 Dartmouth Summer Research Project. This was followed by the golden years (1956-1974), the AI Winter (1974-1980), expert systems in the 1980s, an AI 'chill' (1987-1993), and a period of growing data and compute from 1993 to 2011.

**Source:** `Week01-LectureB-History-Of-Machine-Learning.md`: "it was here that the term 'artificial intelligence' was coined"

**Misconceptions:**
- The term artificial intelligence was coined in the 1980s. (quiz distractor)
- Advancement slowed in the 1970s because of conflicts between countries. (quiz distractor)
- Charles Babbage, the 19th century pioneer, was a 20th century AI researcher who coined the term. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 4. GO_01_03_002 (week 1): Explain Ai Winters

1. what was the AI winter and why did it happen?
2. what decade was the AI winter?
3. what did you mean by combinatorial explosion? (follow-up to 1)

**Reference answer:** The AI Winter was a period from about 1974 to 1980 when funding dried up and confidence in the field slowed. The complexity of making intelligent machines had been understated and the promise overblown given the available compute power. Problems included limited compute, combinatorial explosion, too little data, and criticism of the approaches used.

**Source:** `Week01-LectureB-History-Of-Machine-Learning.md`: "By the mid 1970s, it had become apparent that the complexity of making 'intelligent machines' had been understated and that its promise, given the available compute power, had been overblown."

**Misconceptions:**
- The AI Winter occurred in the 1950s or 1960s. (quiz distractor)
- The AI winter happened because there weren't enough skilled engineers. (quiz distractor)
- The AI winter was caused by AI being too successful and being banned. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 5. GO_02_05_002 (week 2): Inference Engine Mechanism

1. what does the inference engine do in an expert system?
2. why do they say knowledge should be separate from inference?
3. why does that matter? (follow-up to 2)

**Reference answer:** The inference engine orchestrates the process of searching the problem state space, asking the user questions when needed. It also finds the right rules to apply to each state. Keeping knowledge separate from inference lets a domain expert write rules without understanding how inference works.

**Source:** `Week02-LectureA-Knowledge-Representation-And-Expert-Systems.md`: "Inference engine**: orchestrates the whole process of searching in the problem state space, asking questions of the user when necessary. It is also responsible for finding the right rules to be applied"

**Misconceptions:**
- The inference engine stores the expert's long-term knowledge. (common error)
- Expert systems are best written directly in a programming language with rules mixed into the code. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 6. GO_02_05_003 (week 2): Forward Chaining Process

1. how does forward chaining work step by step?
2. what is a conflict set and how do you pick a rule from it?
3. can you show that with the animal example? (follow-up to 1)

**Reference answer:** Forward inference starts with initial data in working memory and runs a reasoning loop. It stops if the target attribute is present; otherwise it finds all rules whose conditions are satisfied (the conflict set), picks one by conflict resolution, applies it to add new knowledge, and repeats. For example, facts like sharp teeth, claws and forward-looking eyes fire the carnivore rule, adding a new fact.

**Source:** `Week02-LectureA-Knowledge-Representation-And-Expert-Systems.md`: "It starts with some initial data about the problem available in the working memory, and then executes the following reasoning loop:"

**Misconceptions:**
- Forward inference starts by looking for a goal. (quiz distractor)
- Forward inference starts over after each rule is applied. (quiz distractor)
- Conflict resolution always picks a random rule. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 7. GO_03_07_001 (week 3): Define Machine Learning

1. what is machine learning, in simple terms?
2. is machine learning supposed to copy how the human brain learns?
3. can you give me an example of that? (follow-up to 1)

**Reference answer:** Machine learning is the creation of automated systems that can learn hidden patterns from data to help make intelligent decisions. It is loosely inspired by how the human brain learns from the data it perceives. Examples include predicting disease likelihood or weather events.

**Source:** `Week03-LectureA-Introduction-To-Machine-Learning.md`: "Machine learning, from a systems perspective, is defined as the creation of automated systems that can learn hidden patterns from data to aid in making intelligent decisions."

**Misconceptions:**
- Machine learning algorithms are meant to simulate intelligent machines. (quiz distractor)
- Machine learning is only used in a few niche areas and isn't really all around us. (quiz distractor)
- Machine learning means a programmer writes every rule by hand for the computer to follow. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 8. GO_03_08_001 (week 3): Define Ml Problem Statement

1. what should the first step of building an ML model be?
2. when is ML better than just writing rules?
3. can you give me an example of that? (follow-up to 2)

**Reference answer:** The first step is to decide on the question. ML fits questions that a simple conditional program or rules-based engine can't answer, often predictions from a collection of data. For example, predicting mortality from many health variables, or weather for April.

**Source:** `Week03-LectureB-Techniques-Of-Machine-Learning.md`: "Most ML processes start by asking a question that cannot be answered by a simple conditional program or rules-based engine."

**Misconceptions:**
- You should start by choosing a training method before you know your question. (quiz distractor)
- ML is only useful to automate multi-dimensional problems, not customizing things like a shopping experience. (quiz distractor)
- Any question can be solved just as well with a hard-coded rules engine. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 9. GO_03_08_003 (week 3): Train/Test Split Execution

1. how do I split my data for training?
2. what are the training, testing and validation sets for?
3. why not just test on the same data I trained on? (follow-up to 2)

**Reference answer:** Before training you split the dataset into two or more parts of unequal size that still represent the data well. The training set is the majority and is fit to the model. The test set is independent data to confirm performance, and an optional smaller validation set tunes hyperparameters.

**Source:** `Week03-LectureB-Techniques-Of-Machine-Learning.md`: "Prior to training, you need to split your dataset into two or more parts of unequal size that still represent the data well."

**Misconceptions:**
- You split data into training and turing sets. (quiz distractor)
- The split should be into validation and evaluation sets only. (quiz distractor)
- The training and test parts should be equal in size. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 10. GO_03_09_003 (week 3): Regression Model Error Metrics

1. how is the error of a regression model measured?
2. what is the coefficient of determination?
3. why do they square the distances? (follow-up to 1)

**Reference answer:** Error can be measured with root mean square error (RMSE), the root of the mean of all squared differences between expected and predicted values. Another quality indicator is the coefficient of determination, where 0 means the model is no better than the mean and 1 means perfect prediction.

**Source:** `Week03-LectureC-Linear-Regression.md`: "root mean square error (RMSE) metrics, which is the root of the mean of all squared differences between expected and predicted value."

**Misconceptions:**
- RMSE is the average of the raw differences, so positive and negative errors cancel. (common error)
- A coefficient of determination of 0 means the model predicts perfectly. (lesson)
- Squaring the distances treats large errors the same as small ones. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 11. GO_03_09_004 (week 3): Error Measurement Application

1. how do I measure the error for one data point in least squares?
2. if my RMSE is about 2 on pumpkin prices, is that good?
3. how would I get that number in code? (follow-up to 2)

**Reference answer:** For each data point you measure the vertical distance, called a residual, between the actual point and the regression line. In the pumpkin example, predicting on the test set gave an RMSE of about 2 points, roughly 17%. The lesson calls that not too good, and the coefficient of determination was low too.

**Source:** `Week03-LectureC-Linear-Regression.md`: "For every data point, we measure the vertical distance (called a residual) between the actual point and our regression line."

**Misconceptions:**
- The residual is the horizontal distance between the point and the line. (common error)
- You should measure error on the training data rather than on test data. (common error)
- Stepwise, Ridge, Lariat and Elasticnet are the regression methods. (quiz distractor)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 12. GO_04_10_001 (week 4): Neuron Structure Identification

1. what is a threshold logic unit?
2. what are the parts of the simple neuron model, like inputs and weights?
3. how did they actually set the weights in the first one? (follow-up to 1)

**Reference answer:** A threshold logic unit is another name for the simple single neuron used in Rosenblatt's early perceptron network. That network had 400 inputs from a photocell array and one binary output. Its weights acted like potentiometers that were adjusted by hand during training.

**Source:** `Week04-LectureB-Perceptron.md`: "A simple network contained one neuron, also called a **threshold logic unit**. Neural network weights acted like potentiometers that required manual adjustment during the training phase."

**Misconceptions:**
- A threshold logic unit is a different thing from a simple neuron, like a separate kind of chip. (quiz distractor)
- The first perceptron had many outputs, one for each shape it recognized. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 13. GO_04_11_001 (week 4): Perceptron Algorithm Basics

1. what are we trying to find when we train a perceptron?
2. what is the perceptron criterion?
3. why does that matter for training? (follow-up to 1)

**Reference answer:** Training a perceptron means finding a weights vector that classifies most values correctly, which gives the smallest error. The error is defined by the perceptron criterion, which sums over the wrongly classified training points.

**Source:** `Week04-LectureB-Perceptron.md`: "To train a perceptron we need to find a weights vector w that classifies most of the values correctly, i.e. results in the smallest **error**."

**Misconceptions:**
- Training a perceptron looks for the smallest size of the weights vector. (quiz distractor)
- Training tries to find the fewest nodes needed. (quiz distractor)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 14. GO_04_11_004 (week 4): Binary Classification With Perceptron

1. what kind of model is a perceptron?
2. how did we use a perceptron on MNIST digits?
3. so how would you do all 10 digits then? (follow-up to 2)

**Reference answer:** A perceptron is a binary classification model, meaning it separates two classes of input data. On MNIST it was applied to two digits at a time, such as 1 versus 0, one as the positive class and the other as the negative class.

**Source:** `Week04-LectureB-Perceptron.md`: "A perceptron is a **binary classification** model, i.e. it can distinguish between two classes of input data."

**Misconceptions:**
- A perceptron is a multi-class classification model that picks among 10 digits directly. (quiz distractor)
- A perceptron is a clustering model that finds groups without labels. (quiz distractor)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 15. GO_05_12_003 (week 5): Loss Function Minimization

1. Why is training a network described as minimizing the loss?
2. What is cross-entropy loss and when is it 0?
3. is binary cross-entropy the same thing as log loss? (follow-up to 2)

**Reference answer:** Given a dataset, the loss becomes a function of the parameters theta, so training means finding the theta that gives the smallest loss. Cross-entropy loss compares the network's probability distribution with the one-hot true distribution, computed as -log p_c. It is 0 when the network gives probability 1 to the expected class and grows toward infinity as that probability nears 0.

**Source:** `Week05-LabA-Own-Framework.ipynb`: "If the network return probability 1 for the expected class, cross-entropy loss would be 0. The closer the probability of the actual class is to 0, the higher is cross-entropy loss"

**Misconceptions:**
- Binary cross-entropy is a different loss from log loss. (quiz distractor)
- Cross-entropy can only compare a network output to a single number, not two probability distributions. (quiz distractor)
- Lower probability for the correct class gives lower cross-entropy loss. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 16. GO_05_14_001 (week 5): Framework Abstraction Layers

1. what does a framework like PyTorch or Keras actually do for me that plain numpy doesn't?
2. whats the difference between low-level and high-level API in tensorflow and pytorch?
3. can you give me an example of when i'd pick the low-level one? (follow-up to 2)

**Reference answer:** Frameworks add layers of abstraction on top of raw tensor math. The low-level API works with tensors and computational graphs and computes gradients automatically, on CPU or GPU. The high-level API (Keras, PyTorch Lightning) treats a network as a sequence of layers so you can build typical networks quickly without worrying about lots of details.

**Source:** `Week05-LectureB-Frameworks-And-Overfitting.md`: "The high-level API allows you to construct typical neural networks very quickly without worrying about lots of details."

**Misconceptions:**
- Keras and PyTorch are completely separate things, and the high-level API can't be combined with low-level code. (lesson)
- High-level APIs are always better, so nobody needs the low-level API. (common error)
- A framework just adds a faster version of numpy and nothing else. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 17. GO_05_14_003 (week 5): Model Training Utilities

1. how do keras and pytorch help with training a model?
2. what does fit do in keras?
3. why does it matter that training can run on a GPU? (follow-up to 1)

**Reference answer:** High-level APIs make training simple: you prepare the data and call a `fit` function to do the job. Frameworks also provide optimizers beyond plain gradient descent and let computation run on GPU, which matters because deep network training needs a lot of computation.

**Source:** `Week05-LectureB-Frameworks-And-Overfitting.md`: "Training the model usually requires preparing the data and then calling a `fit` function to do the job."

**Misconceptions:**
- After compiling a Keras model you train it by calling a train or teach function. (quiz distractor)
- Deep neural network training doesn't need much computation, so GPUs aren't important. (quiz distractor)
- Calling fit means you don't need to understand what training is doing. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 18. GO_05_14_004 (week 5): Framework Ecosystem Support

1. which company made tensorflow and which made pytorch?
2. how does Keras relate to TensorFlow and PyTorch?
3. so which one should I pick for this course? (follow-up to 2)

**Reference answer:** TensorFlow came from Google and PyTorch is a framework from Facebook. Keras is a higher-level API on top of TensorFlow or PyTorch that unifies and simplifies using neural networks, and in TensorFlow 2.x it is integrated. The course offers content for both, so you can choose your preferred one.

**Source:** `Week05-LabC-Intro-To-PyTorch.ipynb`: "PyTorch - a framework from Facebook that is growing in popularity"

**Misconceptions:**
- TensorFlow is from Facebook and PyTorch is from Google. (quiz distractor)
- Keras is a completely independent framework unrelated to TensorFlow. (common error)
- You must learn both frameworks to do the course notebooks. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 19. GO_06_16_001 (week 6): Fairness In Ai Systems

1. what does fairness mean for an AI system?
2. how does biased training data end up making a model biased?
3. can you give me an example of that? (follow-up to 2)

**Reference answer:** Fairness means AI systems should treat everyone fairly and not affect similar groups of people in different ways. Models can pick up bias from biased training data, for example a job-prediction model favoring males because the training data leaned toward a male audience. To avoid this we need to balance the training data and check the model.

**Source:** `Week06-LectureA-Responsible-AI.md`: "when we try to predict the probability of getting a software developer job for a person, the model is likely to give higher preference to males - just because the training dataset was likely biased towards a male audience."

**Misconceptions:**
- It is not ethical to use AI in medicine at all. (quiz distractor)
- Ethical AI only matters because AI is a powerful tool that can cause harm, and discrimination is not a concern. (quiz distractor)
- Bias in a model only happens when someone deliberately puts it there. (lesson)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---

## 20. GO_06_17_002 (week 6): Fairness Metrics In Ai

1. what are the main kinds of fairness-related harm?
2. what is Fairlearn used for?
3. can you explain the second one you listed? (follow-up to 1)

**Reference answer:** The lesson lists allocation, quality of service, denigration, over- or under-representation, and stereotyping as the main fairness-related harms. Fairlearn is the fairness dashboard tool in Microsoft's Responsible AI Toolbox.

**Source:** `Week06-LectureB-Fairness-In-Machine-Learning.md`: "Allocation, if a gender or ethnicity for example is favored over another."

**Misconceptions:**
- Model fairness is mainly about interpretability rather than bias. (quiz distractor)
- Fairlearn decides for you what is fair and what is not. (quiz distractor)
- Fairness harms are only about whether a group gets resources, not about service quality or stereotypes. (common error)

- [ ] Questions are on this objective and sound like a student
- [ ] The follow-up refers back naturally
- [ ] The reference answer is correct and matches the lesson
- [ ] The source file and quote support it
- [ ] The misconceptions are plausible and actually wrong

Notes:

---
