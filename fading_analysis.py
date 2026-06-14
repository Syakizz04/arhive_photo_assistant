"""
Module 3 — Fading Analysis & Object Tagging
==========================================

Responsibilities:
    * Color histogram analysis
    * Sepia/fading detection
    * Basic object detection or image captioning

This module consumes the metadata JSON produced by preprocessing.py. It reads
`processed_color_path`, crops to `analysis.content_box`, then computes:

{
  "fading": "Moderate",
  "tags": ["building", "people", "street"]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List

import cv2
import numpy as np


def _resolve_path(
    path: str | Path,
    base_dir: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> Path:
    """Resolve relative paths from preprocessing's metadata contract."""
    path = Path(path)
    if path.is_absolute():
        return path

    search_roots: list[Path] = []
    if base_dir is not None:
        search_roots.append(Path(base_dir))
    search_roots.append(Path.cwd())
    if metadata_path is not None:
        metadata_parent = Path(metadata_path).resolve().parent
        search_roots.extend([metadata_parent, metadata_parent.parent])

    for root in search_roots:
        candidate = root / path
        if candidate.exists():
            return candidate

    return (search_roots[0] / path) if search_roots else path


def load_color_image(
    image_path: str | Path,
    base_dir: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> np.ndarray:
    """Load a color image from disk as BGR."""
    resolved_path = _resolve_path(image_path, base_dir, metadata_path)
    image = cv2.imread(str(resolved_path), cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError(f"Could not read color image: {resolved_path}")

    return image


def crop_to_content_box(
    image: np.ndarray,
    content_box: list[int] | tuple[int, int, int, int] | None,
) -> np.ndarray:
    """Crop to the real photo area and ignore preprocessing's black padding."""
    if content_box is None:
        return image

    if len(content_box) != 4:
        raise ValueError("content_box must be [x, y, width, height].")

    x, y, width, height = [int(value) for value in content_box]
    img_h, img_w = image.shape[:2]

    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(img_w, x + width)
    y2 = min(img_h, y + height)

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"Invalid content_box for image size {img_w}x{img_h}: {content_box}")

    return image[y1:y2, x1:x2]


def _image_region_from_metadata(
    metadata: dict[str, Any],
    base_dir: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> np.ndarray:
    """Load the preprocessed color image and crop it to content_box."""
    if metadata.get("status") != "ok":
        raise ValueError(f"Skipping image because preprocessing status is {metadata.get('status')!r}.")

    color_path = metadata.get("processed_color_path")
    if not color_path:
        raise KeyError("Metadata is missing processed_color_path.")

    color = load_color_image(color_path, base_dir=base_dir, metadata_path=metadata_path)
    content_box = metadata.get("analysis", {}).get("content_box")
    return crop_to_content_box(color, content_box)


def calculate_color_fading(image: np.ndarray) -> str:
    """Analyze color saturation to classify fading severity for color images."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    mean_saturation = np.mean(saturation)
    std_saturation = np.std(saturation)
    
    # Heuristic thresholds based on typical archival photo characteristics
    if mean_saturation > 120 and std_saturation > 40:
        return "None"
    elif mean_saturation > 80 and std_saturation > 30:
        return "Mild"
    elif mean_saturation > 40 and std_saturation > 20:
        return "Moderate"
    else:
        return "Severe"


def calculate_tonal_fading(image: np.ndarray) -> str:
    """Analyze tonal range to classify fading severity for grayscale/sepia images."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
    
    # Find dynamic range - how many bins have significant pixels
    non_zero = np.where(hist > 0.01 * np.sum(hist))[0]
    if len(non_zero) < 2:
        return "Severe"
    
    min_intensity = non_zero[0]
    max_intensity = non_zero[-1]
    range_width = max_intensity - min_intensity
    
    # Thresholds for dynamic range
    if range_width > 180:
        return "None"
    elif range_width > 120:
        return "Mild"
    elif range_width > 60:
        return "Moderate"
    else:
        return "Severe"


def detect_sepia_tone(image: np.ndarray) -> bool:
    """Detect if a grayscale-looking image has sepia/yellowish tones."""
    b, g, r = cv2.split(image.astype(np.float32))
    avg_b = np.mean(b)
    avg_g = np.mean(g)
    avg_r = np.mean(r)
    
    # Sepia typically has red channel highest, then green, then blue
    if avg_r > avg_g and avg_g > avg_b and (avg_r - avg_b) > 10:
        return True
    return False


def analyze_fading(image: np.ndarray, is_grayscale: bool) -> str:
    """Main fading analysis function that handles both color and grayscale/sepia images."""
    if is_grayscale:
        # Check if it's actually sepia-toned before using tonal analysis
        if detect_sepia_tone(image):
            # Even for sepia, check if the sepia tones themselves are faded
            return calculate_color_fading(image)
        else:
            # True grayscale - use tonal range analysis
            return calculate_tonal_fading(image)
    else:
        # Color image - use saturation analysis
        return calculate_color_fading(image)


def extract_basic_tags(image: np.ndarray) -> List[str]:
    """Placeholder for object tagging. Returns basic scene tags based on image characteristics.
    
    This can be extended later with an LLM vision API. Currently uses simple heuristics.
    """
    tags = []
    
    # Basic image characteristics that can hint at content
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Edge detection to guess complexity
    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.mean(edges) / 255
    
    # Detect faces (basic people detection)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    if len(faces) > 0:
        tags.append("people")
    
    # Guess based on edge complexity
    if edge_density > 0.15:
        tags.append("building")  # Buildings have lots of edges
        tags.append("architecture")
    elif edge_density > 0.08:
        tags.append("street")
        tags.append("outdoor")
    else:
        tags.append("portrait")
        tags.append("indoor")
    
    # If no tags were added, provide a default
    if not tags:
        tags = ["scene", "archival"]
        
    return list(set(tags))  # Remove duplicates


def assess_fading(
    metadata_or_image: dict[str, Any] | str | Path | np.ndarray,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Return fading classification and basic tags.
    
    Preferred input is the metadata dict from preprocessing.py. For convenience,
    this also accepts a metadata JSON path, image path, or already-loaded image.
    """
    if isinstance(metadata_or_image, dict):
        image = _image_region_from_metadata(metadata_or_image, base_dir=base_dir)
        is_grayscale = metadata_or_image.get("analysis", {}).get("is_grayscale", False)
    elif isinstance(metadata_or_image, (str, Path)):
        input_path = Path(metadata_or_image)
        if input_path.suffix.lower() == ".json":
            with open(input_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            image = _image_region_from_metadata(metadata, base_dir=base_dir, metadata_path=input_path)
            is_grayscale = metadata.get("analysis", {}).get("is_grayscale", False)
        else:
            image = load_color_image(input_path, base_dir=base_dir)
            is_grayscale = False
    else:
        image = metadata_or_image
        is_grayscale = False

    fading_level = analyze_fading(image, is_grayscale)
    tags = extract_basic_tags(image)
    
    return {
        "fading": fading_level,
        "tags": tags
    }


def update_metadata_with_fading(
    metadata: dict[str, Any],
    base_dir: str | Path | None = None,
    metadata_path: str | Path | None = None,
) -> dict[str, Any]:
    """Add this module's fading analysis results into a metadata dictionary."""
    image = _image_region_from_metadata(
        metadata,
        base_dir=base_dir,
        metadata_path=metadata_path,
    )
    is_grayscale = metadata.get("analysis", {}).get("is_grayscale", False)
    
    fading_level = analyze_fading(image, is_grayscale)
    tags = extract_basic_tags(image)
    
    metadata["fading_analysis"] = {
        "fading": fading_level,
        "tags": tags
    }
    return metadata


def process_metadata_file(
    metadata_path: str | Path,
    write_back: bool = True,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Read one preprocessing JSON file, add fading analysis, and optionally save it."""
    metadata_path = Path(metadata_path)
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    if metadata.get("status") != "ok":
        return metadata

    metadata = update_metadata_with_fading(
        metadata,
        base_dir=base_dir,
        metadata_path=metadata_path,
    )

    if write_back:
        with open(metadata_path, "w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

    return metadata


def process_metadata_folder(
    metadata_dir: str | Path = "outputs",
    write_back: bool = True,
    base_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Run Module 3 for every metadata JSON file in a folder."""
    metadata_dir = Path(metadata_dir)
    results: list[dict[str, Any]] = []

    for metadata_path in sorted(metadata_dir.glob("*.json")):
        metadata = process_metadata_file(metadata_path, write_back=write_back, base_dir=base_dir)
        results.append(metadata)

        if metadata.get("status") == "ok":
            print(f"[ok]    {metadata['image_id']}  ->  fading: {metadata['fading_analysis']['fading']}, tags: {metadata['fading_analysis']['tags']}")
        else:
            print(f"[skip]  {metadata.get('image_id', metadata_path.stem)}")

    print(f"\nDone. Fading analyzed for {sum(1 for item in results if 'fading_analysis' in item)}/{len(results)} images.")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Module 3 — fading analysis and object tagging."
    )
    parser.add_argument(
        "--meta",
        default="outputs",
        help="Metadata JSON file or folder from preprocessing.py (default: outputs).",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Project root for resolving relative paths, if needed.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Print fading analysis without writing it back to JSON.",
    )
    args = parser.parse_args()

    metadata_path = Path(args.meta)
    if metadata_path.is_dir():
        process_metadata_folder(
            metadata_path,
            write_back=not args.no_write,
            base_dir=args.base_dir,
        )
    else:
        metadata = process_metadata_file(
            metadata_path,
            write_back=not args.no_write,
            base_dir=args.base_dir,
        )
        if metadata.get("status") == "ok":
            print(metadata["fading_analysis"])
        else:
            print(f"[skip] {metadata.get('image_id', metadata_path.stem)}")


if __name__ == "__main__":
    main()