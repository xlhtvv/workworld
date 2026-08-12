FROM python:3.12-slim
WORKDIR /app
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libmagic1 \
    && rm -rf /var/lib/apt/lists/*
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements-runtime.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-runtime.txt
COPY apps/api/src ./apps/api/src
COPY apps/api/migrations ./apps/api/migrations
COPY alembic.ini ./
COPY schemas ./schemas
COPY scripts/real_postgres_races.py ./scripts/real_postgres_races.py
COPY scripts/real_security_journey.py ./scripts/real_security_journey.py
ENV PYTHONPATH=/app/apps/api/src
CMD ["python", "-m", "workworld_api"]
