FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY services/detect/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY libs ./libs
COPY services/detect ./services/detect
COPY services/tracking ./services/tracking
ENV PYTHONPATH=/srv:/srv/libs

CMD ["python", "-m", "services.detect.main"]
