"""Locally authored synthetic repositories for the system architecture view tests.

They are parsed as data and never imported or executed.
"""

FULL_STACK = {
    "README.md": (
        "# Forge\n\n"
        "Forge trains small generator models for synthetic test data.\n\n"
        "## Problem\n\n"
        "- Teams need realistic test data without copying production records.\n"
    ),
    "backend/app/__init__.py": "",
    "backend/app/main.py": (
        "from fastapi import FastAPI\n"
        "\n"
        "from .api.routes.runs import router as runs_router\n"
        "\n"
        'app = FastAPI(title="Forge")\n'
        "app.include_router(runs_router)\n"
    ),
    "backend/app/api/__init__.py": "",
    "backend/app/api/routes/__init__.py": "",
    "backend/app/api/routes/runs.py": (
        "from fastapi import APIRouter\n"
        "\n"
        "from ...services.runs.service import RunService\n"
        "\n"
        'router = APIRouter(prefix="/api/v1", tags=["Runs"])\n'
        "\n"
        "\n"
        '@router.post("/runs/{run_id}/start")\n'
        "def start_run(run_id: str) -> dict[str, str]:\n"
        "    return RunService().start(run_id)\n"
        "\n"
        "\n"
        "@router.get(\n"
        '    "/runs/{run_id}",\n'
        ")\n"
        "def read_run(run_id: str) -> dict[str, str]:\n"
        "    return RunService().get(run_id)\n"
    ),
    "backend/app/services/__init__.py": "",
    "backend/app/services/runs/__init__.py": "",
    "backend/app/services/runs/service.py": (
        "from ...db.repository import RunRepository\n"
        "from ...ml.trainer import train_model\n"
        "\n"
        "\n"
        "class RunService:\n"
        "    def __init__(self) -> None:\n"
        "        self.repository = RunRepository()\n"
        "\n"
        "    def start(self, run_id: str) -> dict[str, str]:\n"
        "        record = self.repository.load(run_id)\n"
        "        result = train_model(record)\n"
        '        return {"run": run_id, "result": result}\n'
        "\n"
        "    def get(self, run_id: str) -> dict[str, str]:\n"
        "        return self.repository.load(run_id)\n"
    ),
    "backend/app/ml/__init__.py": "",
    "backend/app/ml/model.py": (
        "import torch\n"
        "from torch import nn\n"
        "\n"
        "\n"
        "class Generator(nn.Module):\n"
        "    def __init__(self) -> None:\n"
        "        super().__init__()\n"
        "        self.layers = nn.Sequential(nn.Linear(16, 32), nn.ReLU(), nn.Linear(32, 8))\n"
        "\n"
        "    def forward(self, noise):\n"
        "        return self.layers(noise)\n"
        "\n"
        "\n"
        "def sample(size: int):\n"
        "    return torch.randn(size, 16)\n"
    ),
    "backend/app/ml/trainer.py": (
        "from .model import Generator, sample\n"
        "\n"
        "\n"
        "def train_model(record: dict) -> str:\n"
        "    generator = Generator()\n"
        "    output = generator(sample(4))\n"
        "    return str(output.shape)\n"
    ),
    "backend/app/db/__init__.py": "",
    "backend/app/db/repository.py": (
        "from sqlalchemy import create_engine, text\n"
        "\n"
        "\n"
        "class RunRepository:\n"
        "    def __init__(self) -> None:\n"
        '        self.engine = create_engine("sqlite://")\n'
        "\n"
        "    def load(self, run_id: str) -> dict[str, str]:\n"
        "        with self.engine.connect() as connection:\n"
        '            row = connection.execute(text("select id from runs")).first()\n'
        '        return {"run": run_id, "row": str(row)}\n'
    ),
    "frontend/src/api/client.ts": (
        'import axios from "axios";\n'
        "\n"
        'export const api = axios.create({ baseURL: "http://127.0.0.1:8000" });\n'
    ),
    "frontend/src/components/Layout.tsx": (
        'import type { ReactNode } from "react";\n'
        "\n"
        "export function Section({ title, children }: { title: string; children: ReactNode }) {\n"
        "  return (\n"
        "    <section>\n"
        "      <h2>{title}</h2>\n"
        "      {children}\n"
        "    </section>\n"
        "  );\n"
        "}\n"
        "\n"
        "export function State({ value }: { value: string }) {\n"
        "  return <p>{value}</p>;\n"
        "}\n"
    ),
    "frontend/src/utils/format.ts": (
        "export function date(value: string): string {\n"
        "  return value.slice(0, 10);\n"
        "}\n"
        "\n"
        "export function human(value: string): string {\n"
        "  return value.toUpperCase();\n"
        "}\n"
    ),
    "frontend/src/hooks/useResource.ts": (
        'import { useEffect, useState } from "react";\n'
        'import { api } from "../api/client";\n'
        "\n"
        "export function useResource(path: string): string {\n"
        '  const [value, setValue] = useState("");\n'
        "  useEffect(() => {\n"
        "    api.get(path).then((response) => setValue(String(response.data)));\n"
        "  }, [path]);\n"
        "  return value;\n"
        "}\n"
    ),
    "frontend/src/pages/Dashboard.tsx": (
        'import { useResource } from "../hooks/useResource";\n'
        'import { Section, State } from "../components/Layout";\n'
        'import { date, human } from "../utils/format";\n'
        "\n"
        "export function Dashboard() {\n"
        '  const resource = useResource("/api/v1/runs/latest");\n'
        "  const when = date(resource);\n"
        "  const size = human(resource);\n"
        "  return (\n"
        '    <Section title="Dashboard">\n'
        "      <State value={when} />\n"
        "      <State value={size} />\n"
        "    </Section>\n"
        "  );\n"
        "}\n"
    ),
    "frontend/src/features/runs/RunPage.tsx": (
        'import { useState } from "react";\n'
        'import { api } from "../../api/client";\n'
        'import { Section } from "../../components/Layout";\n'
        "\n"
        "export function RunPage({ runId }: { runId: string }) {\n"
        '  const [status, setStatus] = useState("idle");\n'
        "  async function start() {\n"
        "    const response = await api.post(`/api/v1/runs/${runId}/start`);\n"
        "    setStatus(response.data.result);\n"
        "  }\n"
        "  return (\n"
        '    <Section title="Run">\n'
        "      <button onClick={start}>{status}</button>\n"
        "    </Section>\n"
        "  );\n"
        "}\n"
    ),
    "frontend/src/features/runs/RunHistory.tsx": (
        'import { useEffect, useState } from "react";\n'
        'import { api } from "../../api/client";\n'
        "\n"
        "export function RunHistory({ runId }: { runId: string }) {\n"
        '  const [run, setRun] = useState("");\n'
        "  useEffect(() => {\n"
        "    api.get(`/api/v1/runs/${runId}`).then((response) => setRun(response.data.run));\n"
        "  }, [runId]);\n"
        "  return <p>{run}</p>;\n"
        "}\n"
    ),
}

# A pure Python library: four packages, no routes, no client code, no models or data clients.
LIBRARY = {
    "README.md": "# Textkit\n\nTextkit normalises and summarises plain text records.\n",
    "textkit/__init__.py": "",
    "textkit/core/__init__.py": "",
    "textkit/core/model.py": (
        "class Record:\n"
        "    def __init__(self, text: str) -> None:\n"
        "        self.text = text\n"
        "\n"
        "\n"
        "def parse(line: str) -> Record:\n"
        "    return Record(line.strip())\n"
    ),
    "textkit/core/rules.py": (
        "from .model import Record\n"
        "\n"
        "\n"
        "def validate(record: Record) -> bool:\n"
        "    return bool(record.text)\n"
    ),
    "textkit/core/errors.py": ("class TextkitError(Exception):\n    pass\n"),
    "textkit/io/__init__.py": "",
    "textkit/io/reader.py": (
        "from ..core.model import parse\n"
        "\n"
        "\n"
        "def read_lines(lines: list[str]) -> list:\n"
        "    return [parse(line) for line in lines]\n"
    ),
    "textkit/io/writer.py": (
        "from ..core.rules import validate\n"
        "\n"
        "\n"
        "def write(records: list) -> list[str]:\n"
        "    return [r.text for r in records if validate(r)]\n"
    ),
    "textkit/text/__init__.py": "",
    "textkit/text/tokens.py": ("def tokenize(text: str) -> list[str]:\n    return text.split()\n"),
    "textkit/text/normalise.py": (
        "from ..core.model import Record\n"
        "from .tokens import tokenize\n"
        "\n"
        "\n"
        "def normalise(record: Record) -> str:\n"
        '    return " ".join(tokenize(record.text.lower()))\n'
    ),
    "textkit/report/__init__.py": "",
    "textkit/report/summary.py": (
        "from ..io.reader import read_lines\n"
        "from ..text.normalise import normalise\n"
        "\n"
        "\n"
        "def summarise(lines: list[str]) -> list[str]:\n"
        "    records = read_lines(lines)\n"
        "    return [normalise(record) for record in records]\n"
    ),
    "textkit/report/table.py": (
        "from ..io.writer import write\n"
        "from .summary import summarise\n"
        "\n"
        "\n"
        "def table(lines: list[str]) -> list[str]:\n"
        "    rows = summarise(lines)\n"
        "    return write(rows)\n"
    ),
}

# A customer-service demo laid out like many small full-stack apps: the backend lives in a
# hyphenated folder and imports its own sibling package by an absolute name
# (`python-backend/main.py` -> `airline.agents`), which only resolves from that folder.
HELPDESK = {
    "README.md": (
        "# Helpdesk Agents Demo\n\n"
        "This repository contains a demo of a customer service interface built on an agent "
        "orchestration library.\n\n"
        "It is composed of two parts:\n\n"
        "1. A python backend that handles the agent orchestration logic for airline triage "
        "and seat booking.\n\n"
        "2. A Next.js UI allowing the visualization of the agent orchestration process and "
        "providing a chat interface.\n"
    ),
    "python-backend/main.py": (
        "from fastapi import FastAPI\n"
        "\n"
        "from airline.agents import triage_agent\n"
        "from airline.context import AirlineAgentChatContext\n"
        "\n"
        "app = FastAPI()\n"
        "\n"
        "\n"
        '@app.post("/chat")\n'
        "def chat_endpoint(message: dict) -> dict:\n"
        "    context = AirlineAgentChatContext()\n"
        "    return triage_agent(message, context)\n"
        "\n"
        "\n"
        '@app.get("/chat/state")\n'
        "def chat_state(thread_id: str) -> dict:\n"
        '    return {"thread": thread_id}\n'
    ),
    "python-backend/airline/__init__.py": "",
    "python-backend/airline/agents.py": (
        "from .context import AirlineAgentChatContext\n"
        "from .tools import book_seat, lookup_flight\n"
        "\n"
        "\n"
        "def triage_agent(message: dict, context: AirlineAgentChatContext) -> dict:\n"
        '    flight = lookup_flight(message.get("flight", ""))\n'
        '    return {"flight": flight, "seat": book_seat(flight)}\n'
    ),
    "python-backend/airline/context.py": (
        "class AirlineAgentChatContext:\n"
        "    def __init__(self) -> None:\n"
        '        self.passenger = ""\n'
    ),
    "python-backend/airline/tools.py": (
        "def lookup_flight(number: str) -> dict:\n"
        '    return {"number": number}\n'
        "\n"
        "\n"
        "def book_seat(flight: dict) -> str:\n"
        '    return "12A"\n'
    ),
    "python-backend/airline/guardrails.py": (
        'def relevance_guardrail(text: str) -> bool:\n    return "flight" in text\n'
    ),
    "ui/lib/api.ts": (
        "export async function fetchBootstrapState(threadId: string) {\n"
        "  const response = await fetch(`/chat/state?thread_id=${threadId}`);\n"
        "  return response.json();\n"
        "}\n"
    ),
    "ui/components/Chat.tsx": (
        'import { useState } from "react";\n'
        "\n"
        "export function Chat() {\n"
        '  const [text] = useState("");\n'
        "  async function send() {\n"
        '    await fetch("/chat", { method: "POST", body: text });\n'
        "  }\n"
        "  return <button onClick={send}>{text}</button>;\n"
        "}\n"
    ),
    "ui/components/AgentPanel.tsx": (
        'import { Chat } from "./Chat";\n'
        "\n"
        "export function AgentPanel() {\n"
        "  return <section><Chat /></section>;\n"
        "}\n"
    ),
    "ui/app/page.tsx": (
        'import { AgentPanel } from "@/components/AgentPanel";\n'
        "\n"
        "export default function Home() {\n"
        "  return <main><AgentPanel /></main>;\n"
        "}\n"
    ),
    "ui/app/layout.tsx": (
        'import type { ReactNode } from "react";\n'
        "\n"
        "export default function RootLayout({ children }: { children: ReactNode }) {\n"
        "  return <html><body>{children}</body></html>;\n"
        "}\n"
    ),
}
