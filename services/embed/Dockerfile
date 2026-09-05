FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
ENV PIP_DEFAULT_TIMEOUT=180 PIP_RETRIES=5

COPY services/embed/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --default-timeout=180 --retries 5 -r requirements.txt

COPY libs ./libs
COPY services/embed ./services/embed
ENV PYTHONPATH=/srv:/srv/libs

CMD ["python", "-m", "services.embed.main"]
