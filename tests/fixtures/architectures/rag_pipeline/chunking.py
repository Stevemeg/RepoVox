def split(document, size):
    return [document[start : start + size] for start in range(0, len(document), size)]
