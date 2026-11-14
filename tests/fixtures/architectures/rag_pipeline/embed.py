def embed(texts):
    return [[float(len(text)), float(text.count(" "))] for text in texts]
