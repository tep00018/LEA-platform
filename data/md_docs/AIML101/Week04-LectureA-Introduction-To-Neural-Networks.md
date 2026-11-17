> Source: Microsoft AI for Beginners, `lessons/3-NeuralNetworks/README.md` (MIT licence, (c) Microsoft Corporation), commit 392d0df. Adapted for LEA: images and quiz links removed.

# Introduction to Neural Networks

As we discussed in the introduction, one of the ways to achieve intelligence is to train a **computer model** or an **artificial brain**. Since the middle of 20th century, researchers tried different mathematical models, until in recent years this direction proved to be hugely successful. Such mathematical models of the brain are called **neural networks**.

> Sometimes neural networks are called *Artificial Neural Networks*, ANNs, in order to indicate that we are talking about models, not real networks of neurons.

## Machine Learning

Neural Networks are a part of a larger discipline called **Machine Learning**, whose goal is to use data to train computer models that are able to solve problems. Machine Learning constitutes a large part of Artificial Intelligence, however, we do not cover classical ML in this curriculum.

> Visit our separate **[Machine Learning for Beginners](http://github.com/microsoft/ml-for-beginners)** curriculum to learn more about classic Machine Learning.

In Machine Learning, we assume that we have some dataset of examples **X**, and corresponding output values **Y**. Examples are often N-dimensional vectors that consist of **features**, and outputs are called **labels**.

We will consider the two most common machine learning problems:

* **Classification**, where we need to classify an input object into two or more classes.
* **Regression**, where we need to predict a numerical number for each of the input samples.

> When representing inputs and outputs as tensors, the input dataset is a matrix of size M&times;N, where M is number of samples and N is the number of features. Output labels Y is the vector of size M.

In this curriculum, we will only focus on neural network models.

## A Model of a Neuron

From biology, we know that our brain consists of neural cells (neurons), each of them having multiple "inputs" (dendrites) and a single "output" (axon). Both dendrites and axons can conduct electrical signals, and the connections between them — known as synapses — can exhibit varying degrees of conductivity, which are regulated by neurotransmitters.

 |
----|----

Thus, the simplest mathematical model of a neuron contains several inputs X<sub>1</sub>, ..., X<sub>N</sub> and an output Y, and a series of weights W<sub>1</sub>, ..., W<sub>N</sub>. An output is calculated as:

where f is some non-linear **activation function**.

> Early models of neuron were described in the classical paper [A logical calculus of the ideas immanent in nervous activity](https://www.cs.cmu.edu/~./epxing/Class/10715/reading/McCulloch.and.Pitts.pdf) by Warren McCullock and Walter Pitts in 1943. Donald Hebb in his book "[The Organization of Behavior: A Neuropsychological Theory](https://books.google.com/books?id=VNetYrB8EBoC)" proposed the way those networks can be trained.

## In this Section

In this section we will learn about:
* Perceptron, one of the earliest neural network models for two-class classification
* Multi-layered networks with a paired notebook how to build our own framework
* Neural Network Frameworks, with these notebooks: PyTorch and Keras/Tensorflow
* Overfitting
