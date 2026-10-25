FROM python:3.13-slim

WORKDIR /opt/sentinel-acceptance

COPY wheelhouse/ /wheelhouse/

RUN python -m pip install --no-cache-dir --find-links=/wheelhouse \
    "atlas-richie-contracts==0.2.0" \
    "atlas-richie-sentinel-console==0.1.0" \
    "aiosqlite>=0.20,<1.0" \
    && python -m pip cache purge

COPY seed_incident_retention.py /opt/sentinel-acceptance/seed_incident_retention.py

USER 10001:10001

ENTRYPOINT ["python", "/opt/sentinel-acceptance/seed_incident_retention.py"]
