FROM python:3.12.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /usr/local/bin/uv
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-cache
COPY apps/api apps/api
COPY tools tools
COPY docs docs
COPY tests tests
COPY README.md AGENTS.md ./
RUN uv sync --frozen --no-cache && useradd --create-home --uid 10001 repovox && mkdir /storage-config && chown repovox /storage-config
ENV PATH="/workspace/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER repovox
CMD ["uvicorn", "repovox.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
