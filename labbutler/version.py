"""Application version, read once at import time from pyproject.toml.

pyproject.toml is the single source of truth for the version; never hardcode it
elsewhere. The Dockerfile copies pyproject.toml into the image, so this works in
both dev and prod.
"""

import re
import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

with _PYPROJECT.open("rb") as fh:
    __version__: str = tomllib.load(fh)["project"]["version"]

# Git tags put a hyphen before the pre-release segment (v1.0.0-rc1), while
# PEP 440 versions in pyproject.toml do not (1.0.0rc1).
git_tag = "v" + re.sub(r"(?<=\d)(a|b|rc)", r"-\1", __version__, count=1)
release_url = f"https://github.com/gebauer/labbutler/releases/tag/{git_tag}"
