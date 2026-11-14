class Memory:
    def __init__(self):
        self.notes = []

    def remember(self, item):
        self.notes.append(item)

    def recall(self):
        return list(self.notes)


class Planner:
    def plan(self, goal):
        return [part.strip() for part in goal.split(",")]


class Researcher:
    def investigate(self, task, memory):
        return {"task": task, "known": memory.recall()}


class Writer:
    def draft(self, findings):
        return "; ".join(str(finding["task"]) for finding in findings)


class Critic:
    def review(self, draft):
        return {"draft": draft, "approved": bool(draft)}
