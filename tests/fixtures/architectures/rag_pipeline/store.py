class VectorStore:
    def __init__(self, path):
        self.path = path
        self.rows = []

    def add(self, vectors, chunks):
        self.rows.extend(zip(vectors, chunks, strict=True))

    def search(self, vector, limit):
        ranked = sorted(self.rows, key=lambda row: abs(row[0][0] - vector[0][0]))
        return [chunk for _, chunk in ranked[:limit]]
