FROM python:3.12.12-slim
WORKDIR /workspace
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libseccomp2 && update-ca-certificates --fresh && rm -rf /var/lib/apt/lists/*
COPY tools/security_bootstrap.py tools/security_trust.py tools/requirements-bootstrap.txt tools/
RUN python tools/security_bootstrap.py --repair-ensurepip && python tools/security_trust.py --uv --seed
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-cache
COPY apps/api apps/api
COPY tools tools
COPY docs docs
COPY tests tests
COPY infrastructure/retention infrastructure/retention
COPY infra/aws-retention infra/aws-retention
COPY README.md AGENTS.md ./
RUN uv sync --frozen --no-cache && .venv/bin/python tools/security_trust.py --certifi --seed && useradd --create-home --uid 10001 repovox && mkdir /storage-config && chown repovox /storage-config
ENV PATH="/workspace/.venv/bin:$PATH" PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/repovox-pytest-cache"
USER repovox
CMD ["uvicorn", "repovox.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
