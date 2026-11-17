# Jupyter Notebook: Week02-LabC-Concept-Graph.ipynb

## Cell 1 (Markdown)
## Concept Graph using ConceptNet

> **Note:** The original [Microsoft Concept Graph](https://concept.research.microsoft.com/) API is no longer available. This notebook has been updated to use [ConceptNet](https://conceptnet.io/) as a replacement, which is a freely available open knowledge graph with similar `is-a` relations between concepts.

[ConceptNet](https://conceptnet.io/) is a large semantic network of concepts with relationships such as `IsA`, `PartOf`, `UsedFor`, and more. It is available as:
 * A downloadable data file
 * A REST API (no API key required)

ConceptNet statistics:
 * Over 8 million nodes
 * 21+ million edges across 83 languages


## Cell 2 (Markdown)
## Using ConceptNet Web Service

[ConceptNet](https://conceptnet.io/) provides a REST API to explore `is-a` (IsA) relationships between concepts. No API key is required.
Here is the sample URL to call: `https://api.conceptnet.io/query?start=/c/en/microsoft&rel=/r/IsA&limit=10`


## Cell 3 (Code)
```python
import urllib
import json

def http(x):
    response = urllib.request.urlopen(x)
    data = response.read()
    return data.decode('utf-8')

def query(x):
    concept = x.lower().replace(' ', '_')
    url = "https://api.conceptnet.io/query?start=/c/en/{}&rel=/r/IsA&limit=10".format(
        urllib.parse.quote(concept))
    try:
        result = json.loads(http(url))
    except Exception:
        return {}
    edges = result.get('edges', [])
    if not edges:
        return {}
    total_weight = sum(edge['weight'] for edge in edges)
    if total_weight == 0:
        return {}
    return {edge['end']['label']: edge['weight'] / total_weight for edge in edges}

query('microsoft')
```

## Cell 4 (Markdown)
Let's try to categorize the news titles using parent concepts. To get news titles, we will use [NewsApi.org](http://newsapi.org) service. You need to obtain your own API key in order to use the service - go to the web site and register for free developer plan.


## Cell 5 (Code)
```python
newsapi_key = '<your API key here>'
def get_news(country='us'):
    res = json.loads(http("https://newsapi.org/v2/top-headlines?country={0}&apiKey={1}".format(country,newsapi_key)))
    return res['articles']

all_titles = [x['title'] for x in get_news('us')+get_news('gb')]
```

## Cell 6 (Code)
```python
all_titles
```

## Cell 7 (Markdown)
First of all, we want to be able to extract nouns from news titles. We will use `TextBlob` library to do this, which simplifies a lot of typical NLP tasks like this.


## Cell 8 (Code)
```python
import sys
!{sys.executable} -m pip install textblob
!{sys.executable} -m textblob.download_corpora
from textblob import TextBlob
```

## Cell 9 (Code)
```python
w = {}
for x in all_titles:
    for n in TextBlob(x).noun_phrases:
        if n in w:
            w[n].append(x)
        else:
            w[n]=[x]
{ x:len(w[x]) for x in w.keys()}
```

## Cell 10 (Markdown)
We can see that nouns do not give us large thematic groups. Let's substitute nouns by more general terms obtained from the concept graph. This will take some time, because we are doing REST call for each noun phrase.


## Cell 11 (Code)
```python
w = {}
for x in all_titles:
    for noun in TextBlob(x).noun_phrases:
        terms = query(noun)
        for term in [u for u in terms.keys() if terms[u]>0.1]:
            if term in w:
                w[term].append(x)
            else:
                w[term]=[x]
```

## Cell 12 (Code)
```python
{ x:len(w[x]) for x in w.keys() if len(w[x])>3}
```

## Cell 13 (Code)
```python
print('\nECONOMY:\n'+'\n'.join(w['economy']))
print('\nNATION:\n'+'\n'.join(w['nation']))
print('\nPERSON:\n'+'\n'.join(w['person']))
```
