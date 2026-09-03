from black_ice_common.schemas import DetectionMsg, EmbeddingMsg, FrameMsg


def test_frame_msg_roundtrip():
    jpg_bytes = b"\xff\xd8\xff\xd9fake-jpeg"
    msg = FrameMsg(frame_id="f1", camera_id="cam-0", ts=1.0, jpg_b64=FrameMsg.encode_jpg(jpg_bytes))
    restored = FrameMsg.from_json(msg.to_json())
    assert restored == msg
    assert restored.jpg_bytes() == jpg_bytes


def test_detection_msg_roundtrip():
    msg = DetectionMsg(
        frame_id="f1", camera_id="cam-0", ts=1.0, track_id=3,
        bbox=[1.0, 2.0, 3.0, 4.0], kps=[[1.0, 1.0]] * 5, det_score=0.9,
        crop_jpg_b64="Zm9v",
    )
    assert DetectionMsg.from_json(msg.to_json()) == msg


def test_embedding_msg_roundtrip():
    msg = EmbeddingMsg(
        frame_id="f1", camera_id="cam-0", ts=1.0, track_id=3,
        bbox=[1.0, 2.0, 3.0, 4.0], embedding=[0.1] * 512,
    )
    assert EmbeddingMsg.from_json(msg.to_json()) == msg
