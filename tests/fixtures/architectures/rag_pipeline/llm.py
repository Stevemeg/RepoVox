class LocalModel:
    def complete(self, prompt):
        return prompt.splitlines()[-1]
