FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 build-essential postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY services/match/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/match ./services/match
COPY scripts ./scripts
COPY ml/models ./ml/models
ENV PYTHONPATH=/srv:/srv/libs

EXPOSE 8000
CMD ["uvicorn", "services.match.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
