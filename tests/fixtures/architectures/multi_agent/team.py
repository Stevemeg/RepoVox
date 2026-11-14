from agents import Critic, Memory, Planner, Researcher, Writer


def run_team(goal):
    memory = Memory()
    planner = Planner()
    researcher = Researcher()
    writer = Writer()
    critic = Critic()
    tasks = planner.plan(goal)
    findings = []
    for task in tasks:
        finding = researcher.investigate(task, memory)
        memory.remember(finding)
        findings.append(finding)
    draft = writer.draft(findings)
    return critic.review(draft)
