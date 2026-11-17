# Jupyter Notebook: Week05-LabB-MNIST-With-Own-Framework.ipynb

## Cell 1 (Markdown)
# MNIST Digit Classification with our own Framework

Lab Assignment from [AI for Beginners Curriculum](https://github.com/microsoft/ai-for-beginners).

### Reading the Dataset

This code download the dataset from the repository on the internet. You can also manually copy the dataset from `/data` directory of AI Curriculum repo.


## Cell 2 (Code)
```python
!rm *.pkl
!wget https://raw.githubusercontent.com/microsoft/AI-For-Beginners/main/data/mnist.pkl.gz
!gzip -d mnist.pkl.gz
```

## Cell 3 (Code)
```python
import pickle
with open('mnist.pkl','rb') as f:
    MNIST = pickle.load(f)
```

## Cell 4 (Code)
```python
labels = MNIST['Train']['Labels']
data = MNIST['Train']['Features']
```

## Cell 5 (Markdown)
Let's see what is the shape of data that we have:


## Cell 6 (Code)
```python
data.shape
```

## Cell 7 (Markdown)
### Splitting the Data

We will use Scikit Learn to split the data between training and test dataset:


## Cell 8 (Code)
```python
from sklearn.model_selection import train_test_split

features_train, features_test, labels_train, labels_test = train_test_split(data,labels,test_size=0.2)

print(f"Train samples: {len(features_train)}, test samples: {len(features_test)}")
```

## Cell 9 (Markdown)
### Instructions

1. Take the framework code from the lesson and paste it into this notebook, or (even better) into a separate Python module
1. Define and train one-layered perceptron, observing training and validation accuracy during training
1. Try to understand if overfitting took place, and adjust layer parameters to improve accuracy
1. Repeat previous steps for 2- and 3-layered perceptrons. Try to experiment with different activation functions between layers.
1. Try to answer the following questions:
    - Does the inter-layer activation function affect network performance?
    - Do we need 2- or 3-layered network for this task?
    - Did you experience any problems training the network? Especially as the number of layers increased.
    - How do weights of the network behave during training? You may plot max abs value of weights vs. epoch to understand the relation.


## Cell 10 (Code)
```python

```
