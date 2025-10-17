# base image
FROM python:3.11-slim

## repolish-start[install]
# install system deps
RUN apt-get update && apt-get install -y build-essential libssl-dev
## repolish-end[install]

# copy + install python deps
COPY pyproject.toml .
RUN pip install --no-cache-dir .
