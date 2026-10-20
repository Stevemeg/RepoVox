FROM python:3.12.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends libseccomp2 && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-cache
COPY apps/api apps/api
COPY tools tools
COPY docs docs
COPY tests tests
COPY infrastructure/retention infrastructure/retention
COPY README.md AGENTS.md ./
RUN uv sync --frozen --no-cache && useradd --create-home --uid 10001 repovox && mkdir /storage-config && chown repovox /storage-config
ENV PATH="/workspace/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/repovox-pytest-cache"
USER repovox
CMD ["uvicorn", "repovox.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
