FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SENTINEL_CONSOLE_BIND_HOST=0.0.0.0 \
    SENTINEL_CONSOLE_PORT=8000

WORKDIR /opt/sentinel

# The build context must contain a wheelhouse with the Console and its local
# foundation contract wheel. Third-party runtime dependencies are resolved
# from the configured Python package index during image build.
COPY wheelhouse/ /opt/sentinel/wheelhouse/

RUN python -m pip install --no-cache-dir \
      /opt/sentinel/wheelhouse/atlas_richie_contracts-*.whl \
      /opt/sentinel/wheelhouse/atlas_richie_sentinel_console-*.whl \
      'uvicorn>=0.30,<1.0' \
      'anycorn>=0.20,<1.0' \
      'aiosqlite>=0.20,<1.0' \
      'psycopg[binary]>=3.2,<4.0' \
      'asyncmy==0.2.16' \
      'grpcio>=1.66.1,<2.0' \
      'protobuf>=5.27.2,<8.0' \
    && rm -rf /opt/sentinel/wheelhouse \
    && groupadd --system --gid 10001 sentinel \
    && useradd --system --uid 10001 --gid sentinel --home-dir /nonexistent sentinel \
    && mkdir -p /var/lib/sentinel \
    && chown sentinel:sentinel /var/lib/sentinel

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["sentinel-console", "serve"]
