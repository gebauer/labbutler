"""Application version and build commit, resolved once at import time.

pyproject.toml is the single source of truth for the version; never hardcode it
elsewhere. The Dockerfile copies pyproject.toml into the image, so this works in
both dev and prod.

The build commit comes from $LABBUTLER_COMMIT (baked into the Docker image via
the GIT_COMMIT build arg, since .git is not in the image) or, in a dev checkout,
from `git rev-parse`.
"""

import os
import re
import subprocess
import tomllib
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

with (_REPO_ROOT / "pyproject.toml").open("rb") as fh:
    __version__: str = tomllib.load(fh)["project"]["version"]

# Git tags put a hyphen before the pre-release segment (v1.0.0-rc1), while
# PEP 440 versions in pyproject.toml do not (1.0.0rc1).
git_tag = "v" + re.sub(r"(?<=\d)(a|b|rc)", r"-\1", __version__, count=1)
release_url = f"https://github.com/gebauer/labbutler/releases/tag/{git_tag}"


def _resolve_commit() -> str | None:
    """Short hash of the commit this build runs, or None if undeterminable."""
    baked = os.environ.get("LABBUTLER_COMMIT")
    if baked:
        return baked
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


commit = _resolve_commit()
commit_url = f"https://github.com/gebauer/labbutler/commit/{commit}" if commit else None
