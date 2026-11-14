from chunking import split
from embed import embed
from llm import LocalModel
from prompt import build_prompt
from store import VectorStore


def index(documents, store):
    for document in documents:
        chunks = split(document, 200)
        vectors = embed(chunks)
        store.add(vectors, chunks)


def answer(question, documents):
    store = VectorStore("index.bin")
    index(documents, store)
    query = embed([question])
    passages = store.search(query, 4)
    prompt = build_prompt(question, passages)
    model = LocalModel()
    return model.complete(prompt)
