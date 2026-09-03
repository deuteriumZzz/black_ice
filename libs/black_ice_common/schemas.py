"""Wire format for the three Kafka topics. Plain JSON, not Avro/schema-registry —
add a registry when a second consumer language or schema evolution actually shows up."""
import base64
import json
from dataclasses import asdict, dataclass, field


@dataclass
class FrameMsg:
    frame_id: str
    camera_id: str
    ts: float
    jpg_b64: str

    @staticmethod
    def encode_jpg(jpg_bytes: bytes) -> str:
        return base64.b64encode(jpg_bytes).decode("ascii")

    def jpg_bytes(self) -> bytes:
        return base64.b64decode(self.jpg_b64)

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "FrameMsg":
        return cls(**json.loads(raw))


@dataclass
class DetectionMsg:
    frame_id: str
    camera_id: str
    ts: float
    track_id: int
    bbox: list[float]  # full-frame coordinates, for downstream display/audit
    kps: list[list[float]]  # 5x2 landmarks, already crop-local — see crop_jpg_b64
    det_score: float
    crop_jpg_b64: str

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "DetectionMsg":
        return cls(**json.loads(raw))


@dataclass
class EmbeddingMsg:
    frame_id: str
    camera_id: str
    ts: float
    track_id: int
    bbox: list[float]
    embedding: list[float] = field(repr=False)

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "EmbeddingMsg":
        return cls(**json.loads(raw))
