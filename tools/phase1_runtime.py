"""Local-only recovery smoke. Operates only the RepoVox Compose project."""

import subprocess
import time

import httpx

origin = "http://localhost:3000"
client = httpx.Client(base_url="http://localhost:8000", headers={"origin": origin}, timeout=10)


def compose(*arguments: str) -> None:
    subprocess.run(["docker", "compose", *arguments], check=True)


def wait_job(jid: str) -> dict:
    until = time.monotonic() + 60
    while time.monotonic() < until:
        response = client.get(f"/v1/jobs/{jid}")
        response.raise_for_status()
        job = response.json()
        if job["state"] in ("failed", "cancelled"):
            return job
        time.sleep(1)
    raise AssertionError("Fixture did not settle within 60 seconds")


assert client.get("/health").json()["status"] == "alive"
assert client.get("/ready").json()["generation_available"] is False
response = client.post("/v1/auth/development/sign-in", json={"subject": "sam"})
response.raise_for_status()
client.headers["x-csrf-token"] = client.cookies["rv_csrf"]
response = client.post(
    "/v1/projects",
    json={
        "title": "Recovery smoke (synthetic)",
        "repository_url": "https://github.com/example/demo",
    },
)
response.raise_for_status()
pid = response.json()["id"]
try:
    compose("stop", "redis")
    response = client.post(
        f"/v1/development/projects/{pid}/fixture-jobs",
        json={"fixture": "normal"},
        headers={"idempotency-key": f"recovery-{time.time_ns()}"},
    )
    response.raise_for_status()
    jid = response.json()["id"]
    assert response.json()["state"] == "queued"
    time.sleep(6)
    assert client.get(f"/v1/jobs/{jid}").json()["state"] == "queued"
    print("Redis stopped: admission and durable queued job survived.")
finally:
    compose("start", "redis")
job = wait_job(jid)
assert job["error_code"] == "phase1_fixture_boundary"
assert job["stages"][1]["state"] == "succeeded"
print("Redis recovered: durable outbox delivered, one acquire output, explicit Phase 1 boundary.")
compose("restart", "worker", "dispatcher")
assert client.get(f"/v1/jobs/{jid}").json()["state"] == "failed"
print("Graceful worker/dispatcher restart preserved terminal history.")
assert client.delete(f"/v1/projects/{pid}").status_code == 202
assert client.get(f"/v1/jobs/{jid}").status_code == 404
client.post("/v1/auth/sign-out").raise_for_status()
client.close()
print("Immediate project access revocation and logout confirmed.")
