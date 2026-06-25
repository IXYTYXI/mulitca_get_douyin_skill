import json
import csv
import os
from typing import List
from pathlib import Path


class LocalStorage:
    """Fallback local storage for CSV/JSON export."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, data: List[dict], filename: str) -> str:
        path = self.output_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[Local] Saved {len(data)} records to {path}")
        return str(path)

    def save_csv(self, data: List[dict], filename: str) -> str:
        if not data:
            print(f"[Local] No data to save for {filename}")
            return ""
        path = self.output_dir / filename
        keys = data[0].keys()
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in data:
                clean = {}
                for k, v in row.items():
                    if isinstance(v, dict):
                        clean[k] = v.get("link", str(v))
                    else:
                        clean[k] = v
                writer.writerow(clean)
        print(f"[Local] Saved {len(data)} records to {path}")
        return str(path)
