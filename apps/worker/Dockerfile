FROM python:3.12-slim
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements-runtime.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-runtime.txt
COPY apps/api/src ./apps/api/src
COPY apps/worker/src ./apps/worker/src
COPY schemas ./schemas
ENV PYTHONPATH=/app/apps/api/src:/app/apps/worker/src
CMD ["python", "-m", "workworld_worker"]
