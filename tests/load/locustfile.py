"""Load test against the match service's synchronous API (the interactive path —
the camera-stream path is driven by ingest's FPS, not by request load).

Run: python scripts/fetch_demo_frames.py   # once, populates the sample image
     locust -f tests/load/locustfile.py --host http://localhost:8000
"""
import os
import random

from locust import HttpUser, between, task

SAMPLE_IMAGE = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "eval", "sample_frames", "frame_001.jpg")
API_KEY = os.environ.get("BLACK_ICE_LOAD_TEST_API_KEY", "dev-operator-key")


class BlackIceUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def _image_bytes(self) -> bytes:
        with open(SAMPLE_IMAGE, "rb") as f:
            return f.read()

    @task(5)
    def identify(self):
        self.client.post(
            "/identify",
            files={"file": ("face.jpg", self._image_bytes(), "image/jpeg")},
            headers={"X-API-Key": API_KEY},
            name="/identify",
        )

    @task(1)
    def enroll(self):
        self.client.post(
            "/enroll",
            data={"name": f"load-test-{random.randint(0, 1_000_000)}", "consent": "true"},
            files={"file": ("face.jpg", self._image_bytes(), "image/jpeg")},
            headers={"X-API-Key": "dev-admin-key"},
            name="/enroll",
        )

    @task(2)
    def health(self):
        self.client.get("/health", name="/health")
