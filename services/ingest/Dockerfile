FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
ENV PIP_DEFAULT_TIMEOUT=180 PIP_RETRIES=5

COPY services/ingest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --default-timeout=180 --retries 5 -r requirements.txt

COPY libs ./libs
COPY services/ingest ./services/ingest
# Populated by `python scripts/fetch_demo_frames.py` before `docker compose build` —
# only needed for SOURCE=demo; a real camera/RTSP source doesn't touch this dir.
COPY ml/eval/sample_frames ./ml/eval/sample_frames
ENV PYTHONPATH=/srv:/srv/libs

CMD ["python", "-m", "services.ingest.main"]
