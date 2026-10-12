from dataclasses import dataclass

from repovox.auth.session import DevelopmentSessions
from repovox.core.config import Settings
from repovox.services.jobs import Jobs
from repovox.services.projects import Projects


@dataclass(frozen=True)
class Services:
    settings: Settings
    sessions: DevelopmentSessions
    projects: Projects
    jobs: Jobs
