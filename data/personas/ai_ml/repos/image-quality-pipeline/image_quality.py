import os
import json
import csv
import argparse
from typing import List, Dict
import cv2
import numpy as np

# Default thresholds – tuned on a 120‑image validation set
BLUR_THRESHOLD = 100.0  # variance of Laplacian
EXPOSURE_LOW = 50      # mean V channel value
EXPOSURE_HIGH = 200

def compute_sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = laplacian.var()
    return variance

def compute_exposure(image: np.ndarray) -> float:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    return float(v_channel.mean())

def evaluate_image(path: str) -> Dict:
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Unable to read image: {path}")
    sharpness = compute_sharpness(img)
    exposure = compute_exposure(img)
    result = {
        "filename": os.path.basename(path),
        "sharpness": sharpness,
        "is_blurry": sharpness < BLUR_THRESHOLD,
        "exposure": exposure,
        "exposure_status": (
            "under" if exposure < EXPOSURE_LOW else
            "over" if exposure > EXPOSURE_HIGH else
            "normal"
        ),
    }
    return result

def process_folder(folder: str) -> List[Dict]:
    supported = {".jpg", ".jpeg", ".png"}
    results = []
    for root, _, files in os.walk(folder):
        for f in files:
            if os.path.splitext(f)[1].lower() in supported:
                full_path = os.path.join(root, f)
                try:
                    results.append(evaluate_image(full_path))
                except Exception as e:
                    results.append({"filename": f, "error": str(e)})
    return results

def write_outputs(results: List[Dict], out_dir: str):
    json_path = os.path.join(out_dir, "report.json")
    csv_path = os.path.join(out_dir, "summary.csv")
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(results, jf, indent=2)
    with open(csv_path, "w", newline="", encoding="utf-8") as cf:
        writer = csv.writer(cf)
        writer.writerow(["filename", "sharpness", "is_blurry", "exposure", "exposure_status"])
        for r in results:
            if "error" in r:
                continue
            writer.writerow([
                r["filename"],
                f"{r['sharpness']:.2f}",
                r["is_blurry"],
                f"{r['exposure']:.1f}",
                r["exposure_status"]
            ])
    print(f"Report written to {json_path} and {csv_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch image quality assessment")
    parser.add_argument("input_dir", help="Path to folder containing images")
    parser.add_argument("--output", default=".", help="Directory for JSON/CSV reports")
    args = parser.parse_args()
    results = process_folder(args.input_dir)
    write_outputs(results, args.output)
