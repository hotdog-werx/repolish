FROM python:3.11-slim

## repolish-start[install]
# custom build deps for project X
RUN apt-get update && apt-get install -y locales libpq-dev
## repolish-end[install]

# copy + install python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .
