def build_prompt(question, passages):
    context = "\n".join(passages)
    return f"Context:\n{context}\n\nQuestion: {question}"
