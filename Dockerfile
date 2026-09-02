FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN addgroup --system mcp && adduser --system --ingroup mcp --home /app mcp \
    && mkdir -p /data && chown mcp:mcp /data

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

USER mcp
VOLUME ["/data"]

ENTRYPOINT ["odoo-project-mcp"]

