"""Populates ml/eval/sample_frames/ from InsightFace's own bundled test image, so
SOURCE="demo" ingest has something to loop over without a camera. Not committed to
git (third-party asset) — run this once after installing dependencies."""
import os
import shutil

import insightface


def main() -> None:
    src = os.path.join(os.path.dirname(insightface.__file__), "data", "images", "t1.jpg")
    dest_dir = os.path.join(os.path.dirname(__file__), "..", "ml", "eval", "sample_frames")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "frame_001.jpg")
    shutil.copy(src, dest)
    print(f"copied {src} -> {dest}")


if __name__ == "__main__":
    main()
