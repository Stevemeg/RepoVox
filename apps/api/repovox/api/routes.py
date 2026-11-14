import secrets
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, Security
from fastapi.security import APIKeyCookie

from repovox.auth.session import Identity, digest
from repovox.core.errors import DomainError
from repovox.core.services import Services
from repovox.schemas.requests import (
    AnalysisInput,
    FixtureInput,
    ProjectInput,
    ProjectUpdate,
    SignIn,
)
from repovox.schemas.responses import JobSummary, JobView, MediaJobView, ProjectView
from repovox.services.media_jobs import MediaJobs

router = APIRouter(prefix="/v1")
session_cookie = APIKeyCookie(name="rv_session", auto_error=False)


def services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def authenticated(
    request: Request, cookie: Annotated[str | None, Security(session_cookie)]
) -> Identity:
    return services(request).sessions.authenticate(cookie)


def mutation(request: Request, identity: Annotated[Identity, Depends(authenticated)]) -> Identity:
    csrf = request.headers.get("x-csrf-token", "")
    if request.headers.get("origin") != services(
        request
    ).settings.origin or not secrets.compare_digest(digest(csrf), identity.csrf_hash):
        raise DomainError("csrf_rejected", 403)
    return identity


ReadIdentity = Annotated[Identity, Depends(authenticated)]
WriteIdentity = Annotated[Identity, Depends(mutation)]


@router.post("/auth/development/sign-in")
def sign_in(body: SignIn, request: Request, response: Response) -> dict[str, str]:
    if request.headers.get("origin") != services(request).settings.origin:
        raise DomainError("origin_rejected", 403)
    cookie, csrf = services(request).sessions.sign_in(
        body.subject, request.client.host if request.client else "local"
    )
    response.set_cookie(
        "rv_session",
        cookie,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=services(request).settings.session_seconds,
        path="/",
    )
    response.set_cookie(
        "rv_csrf",
        csrf,
        httponly=False,
        samesite="strict",
        secure=False,
        max_age=services(request).settings.session_seconds,
        path="/",
    )
    return {"environment": services(request).settings.environment}


@router.get("/auth/session")
def session(request: Request, identity: ReadIdentity) -> dict[str, Any]:
    return {
        "id": identity.owner_id,
        "display_name": identity.display_name,
        "email": identity.email,
        "environment": services(request).settings.environment,
        "fixtures_enabled": services(request).settings.fixtures,
        "analysis_enabled": services(request).settings.analysis,
        "video_enabled": services(request).media is not None,
    }


@router.post("/auth/sign-out", status_code=204)
def sign_out(request: Request, response: Response, identity: WriteIdentity) -> None:
    services(request).sessions.sign_out(identity)
    response.delete_cookie("rv_session", path="/")
    response.delete_cookie("rv_csrf", path="/")


@router.get("/projects", response_model=list[ProjectView])
def projects(request: Request, identity: ReadIdentity) -> list[dict[str, Any]]:
    return services(request).projects.list(identity.owner_id)


@router.post("/projects", status_code=201, response_model=ProjectView)
def create_project(body: ProjectInput, request: Request, identity: WriteIdentity) -> dict[str, Any]:
    return services(request).projects.create(identity.owner_id, body)


@router.get("/projects/{project_id}", response_model=ProjectView)
def project(project_id: UUID, request: Request, identity: ReadIdentity) -> dict[str, Any]:
    return services(request).projects.get(identity.owner_id, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectView)
def update_project(
    project_id: UUID, body: ProjectUpdate, request: Request, identity: WriteIdentity
) -> dict[str, Any]:
    return services(request).projects.update(identity.owner_id, project_id, body.title)


@router.delete("/projects/{project_id}", status_code=202)
def delete_project(project_id: UUID, request: Request, identity: WriteIdentity) -> dict[str, Any]:
    deletion = services(request).projects.delete(identity.owner_id, project_id)
    return {"deletion_id": deletion, "access_revoked": True, "cleanup": "pending"}


@router.get("/jobs", response_model=list[JobSummary])
def jobs(request: Request, identity: ReadIdentity) -> list[dict[str, Any]]:
    return services(request).jobs.list(identity.owner_id)


@router.get("/projects/{project_id}/jobs", response_model=list[JobSummary])
def project_jobs(
    project_id: UUID, request: Request, identity: ReadIdentity
) -> list[dict[str, Any]]:
    services(request).projects.get(identity.owner_id, project_id)
    return services(request).jobs.list(identity.owner_id, project_id)


@router.post("/projects/{project_id}/jobs")
def generation_unavailable(project_id: UUID, request: Request, identity: WriteIdentity) -> None:
    services(request).projects.get(identity.owner_id, project_id)
    raise DomainError("secure_acquisition_unavailable", 503)


@router.post(
    "/development/projects/{project_id}/analysis-jobs", status_code=202, response_model=JobView
)
def analysis_job(
    project_id: UUID,
    body: AnalysisInput,
    request: Request,
    identity: WriteIdentity,
    idempotency_key: Annotated[str, Header()],
) -> dict[str, Any]:
    return services(request).jobs.admit_analysis(identity.owner_id, project_id, idempotency_key)


@router.get("/development/jobs/{job_id}/analysis")
def analysis_result(job_id: UUID, request: Request, identity: ReadIdentity) -> dict[str, Any]:
    return services(request).jobs.analysis_result(
        identity.owner_id, job_id, services(request).settings
    )


@router.post(
    "/development/projects/{project_id}/fixture-jobs", status_code=202, response_model=JobView
)
def fixture_job(
    project_id: UUID,
    body: FixtureInput,
    request: Request,
    identity: WriteIdentity,
    idempotency_key: Annotated[str, Header()],
) -> dict[str, Any]:
    return services(request).jobs.admit(
        identity.owner_id, project_id, idempotency_key, body.fixture
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def job(job_id: UUID, request: Request, identity: ReadIdentity) -> dict[str, Any]:
    return services(request).jobs.get(identity.owner_id, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: UUID, request: Request, identity: WriteIdentity) -> dict[str, Any]:
    return services(request).jobs.cancel(identity.owner_id, job_id)


@router.post("/development/jobs/{job_id}/retry", status_code=202, response_model=JobView)
def retry(
    job_id: UUID,
    request: Request,
    identity: WriteIdentity,
    idempotency_key: Annotated[str, Header()],
) -> dict[str, Any]:
    old = services(request).jobs.get(identity.owner_id, job_id)
    if not old["synthetic"]:
        return services(request).jobs.admit_analysis(
            identity.owner_id, old["project_id"], idempotency_key, job_id
        )
    return services(request).jobs.admit(
        identity.owner_id, old["project_id"], idempotency_key, old["fixture"], job_id
    )


def media(request: Request) -> MediaJobs:
    found = services(request).media
    if found is None or not services(request).settings.analysis:
        raise DomainError("video_generation_unavailable", 503)
    return found


@router.post("/projects/{project_id}/video-jobs", status_code=202, response_model=MediaJobView)
def video_job(
    project_id: UUID,
    body: AnalysisInput,
    request: Request,
    identity: WriteIdentity,
    idempotency_key: Annotated[str, Header()],
) -> dict[str, Any]:
    service = media(request)
    services(request).projects.get(identity.owner_id, project_id)
    return service.admit(identity.owner_id, project_id, idempotency_key)


@router.get("/projects/{project_id}/video-jobs", response_model=list[MediaJobView])
def project_video_jobs(
    project_id: UUID, request: Request, identity: ReadIdentity
) -> list[dict[str, Any]]:
    service = media(request)
    services(request).projects.get(identity.owner_id, project_id)
    return service.list(identity.owner_id, project_id)


@router.get("/video-jobs/{job_id}", response_model=MediaJobView)
def video_job_status(job_id: UUID, request: Request, identity: ReadIdentity) -> dict[str, Any]:
    return media(request).get(identity.owner_id, job_id)


@router.post("/video-jobs/{job_id}/cancel", response_model=MediaJobView)
def cancel_video_job(job_id: UUID, request: Request, identity: WriteIdentity) -> dict[str, Any]:
    return media(request).cancel(identity.owner_id, job_id)


def byte_range(header: str | None, size: int) -> tuple[int, int] | None:
    """One satisfiable `bytes=a-b` range, or None to send the whole body."""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].partition("-")
    if not first.isdigit() or (last and not last.isdigit()):
        return None
    start, end = int(first), min(int(last) if last else size - 1, size - 1)
    return (start, end) if start <= end < size else None


@router.get("/video-jobs/{job_id}/videos/{video_id}")
def video(job_id: UUID, video_id: UUID, request: Request, identity: ReadIdentity) -> Response:
    body, _ = media(request).video(identity.owner_id, job_id, video_id)
    headers = {"accept-ranges": "bytes"}
    wanted = byte_range(request.headers.get("range"), len(body))
    if wanted is None:
        return Response(body, media_type="video/mp4", headers=headers)
    start, end = wanted
    headers["content-range"] = f"bytes {start}-{end}/{len(body)}"
    return Response(body[start : end + 1], 206, headers, "video/mp4")


@router.get("/video-jobs/{job_id}/videos/{video_id}/download")
def download_video(
    job_id: UUID, video_id: UUID, request: Request, identity: ReadIdentity
) -> Response:
    body, row = media(request).video(identity.owner_id, job_id, video_id)
    name = f"repovox-{row['category']}-{video_id}.mp4"
    return Response(
        body,
        media_type="video/mp4",
        headers={"content-disposition": f'attachment; filename="{name}"'},
    )


@router.get("/video-jobs/{job_id}/videos/{video_id}/captions")
def video_captions(
    job_id: UUID, video_id: UUID, request: Request, identity: ReadIdentity
) -> Response:
    _, row = media(request).video(identity.owner_id, job_id, video_id)
    return Response(row["captions"], media_type="text/vtt; charset=utf-8")
