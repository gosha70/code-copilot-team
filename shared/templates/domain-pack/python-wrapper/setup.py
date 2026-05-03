# Reads name, version, description from ../content/manifest.yaml so the
# manifest stays the single source of truth across both wrappers.
#
# Note: PyPI package names cannot contain underscores in the canonical form
# but are normalized at install time. The on-disk Python module name is
# `domain_pack` regardless of the dashed pack name.
from __future__ import annotations

from pathlib import Path

import yaml
from setuptools import setup

HERE = Path(__file__).parent.resolve()

# Two locations: dev (../content/manifest.yaml) and synced (src/domain_pack/data/manifest.yaml).
manifest_candidates = [
    HERE.parent / "content" / "manifest.yaml",
    HERE / "src" / "domain_pack" / "data" / "manifest.yaml",
]
manifest_path = next((p for p in manifest_candidates if p.exists()), None)
if manifest_path is None:
    raise RuntimeError(
        "manifest.yaml not found. Run scripts/sync-content.sh before building."
    )

manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

setup(
    version=manifest["version"],
    description=manifest.get("description", ""),
)
