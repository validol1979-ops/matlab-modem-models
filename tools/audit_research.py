#!/usr/bin/env python3
"""Verify the downloaded research collections without executing their code."""
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    # Сравниваем содержимое с исходной свалкой, а не только имена файлов.
    existing = defaultdict(list)
    for directory in ("sources", "arxiv"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file():
                existing[digest(path)].append(str(path.relative_to(ROOT)))
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "collections": []}
    for directory, manifest, key in (
        ("electronix_20260930", "findings.json", "downloaded"),
        ("dsp_global_20260930", "manifest.json", "collections"),
    ):
        base = ROOT / "research" / directory
        manifest_path = base / manifest
        data = json.loads(manifest_path.read_text())
        records = {}
        for item in data[key]:
            for entry in item["files"] + ([item["archive"]] if "archive" in item else []):
                records[entry["path"]] = entry
        result = {"directory": str(base.relative_to(ROOT)), "manifest_sha256": digest(manifest_path),
                  "verified_files": [], "errors": [], "existing_duplicates": [], "zip_crc": []}
        for name, entry in sorted(records.items()):
            path = base / name
            if not path.is_file():
                result["errors"].append({"path": name, "reason": "Missing file"})
                continue
            actual = {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}
            result["verified_files"].append(actual)
            if any(actual[key] != entry[key] for key in ("sha256", "bytes")):
                result["errors"].append({"path": name, "reason": "Manifest mismatch"})
            if actual["sha256"] in existing:
                result["existing_duplicates"].append({"path": name, "matches": existing[actual["sha256"]]})
        for path in sorted(base.rglob("*.zip")):
            try:
                with zipfile.ZipFile(path) as archive:
                    bad = archive.testzip()
                    result["zip_crc"].append({"path": str(path.relative_to(base)),
                                              "members": len(archive.infolist()), "bad_member": bad})
                    if bad:
                        result["errors"].append({"path": str(path), "reason": "ZIP CRC mismatch"})
            except (OSError, zipfile.BadZipFile) as error:
                result["errors"].append({"path": str(path), "reason": str(error)})
        result["file_extensions"] = dict(sorted(Counter(
            path.suffix.lower() for path in base.rglob("*") if path.is_file()).items()))
        result["status"] = "PASS" if not result["errors"] else "FAIL"
        report["collections"].append(result)
        print(f"{result['status']} {directory}: {len(records)} hashes, "
              f"{len(result['zip_crc'])} ZIP archives, {len(result['existing_duplicates'])} existing duplicates")
    destination = ROOT / "build" / "research_review"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "integrity.json").write_text(json.dumps(report, indent=2) + "\n")
    return 1 if any(item["errors"] for item in report["collections"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
