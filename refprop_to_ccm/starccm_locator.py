from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path


STARCCM_EXECUTABLE_NAME = "starccm+.exe"
_SEARCH_PATTERNS = (
    "STAR-CCM*/**/starccm+.exe",
    "STAR_CCM*/**/starccm+.exe",
    "Simcenter STAR-CCM*/**/starccm+.exe",
    "Siemens/STAR-CCM*/**/starccm+.exe",
    "Siemens/Simcenter STAR-CCM*/**/starccm+.exe",
    "Siemens/Simcenter/STAR-CCM*/**/starccm+.exe",
)


def is_starccm_executable(path: str | Path) -> bool:
    candidate = Path(path)
    return (
        candidate.name.lower() == STARCCM_EXECUTABLE_NAME
        and candidate.is_file()
    )


def choose_startup_starccm_path(
    saved_path: str | None,
    discovered_path: Path | None,
) -> str:
    saved_text = str(saved_path or "").strip()
    if saved_text and is_starccm_executable(saved_text):
        return saved_text
    if discovered_path is not None:
        return str(discovered_path)
    return saved_text


def manual_starccm_path_from_config(config: object) -> str | None:
    if not isinstance(config, dict):
        return None
    fields = config.get("fields")
    if not isinstance(fields, dict) or "starccm_exe" not in fields:
        return None
    return str(fields["starccm_exe"]).strip()


def find_starccm_executable(
    *,
    search_roots: Sequence[Path] | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    env = os.environ if environment is None else environment

    explicit_executable = str(env.get("STARCCM_EXE", "")).strip()
    if explicit_executable and is_starccm_executable(explicit_executable):
        return Path(explicit_executable)

    candidates: set[Path] = set()
    starccm_home = str(env.get("STARCCM_HOME", "")).strip()
    if starccm_home:
        candidates.update(_find_candidates_in_root(Path(starccm_home)))

    roots = (
        list(search_roots)
        if search_roots is not None
        else default_starccm_search_roots(environment=env)
    )
    for root in roots:
        candidates.update(_find_candidates_in_root(Path(root)))

    if not candidates:
        return None
    return max(candidates, key=_starccm_candidate_sort_key)


def default_starccm_search_roots(
    *,
    environment: Mapping[str, str] | None = None,
) -> list[Path]:
    env = os.environ if environment is None else environment
    roots: list[Path] = []
    for variable_name in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = str(env.get(variable_name, "")).strip()
        if value:
            roots.append(Path(value))

    for drive in _fixed_windows_drives():
        roots.append(drive / "Program Files")
        roots.append(drive / "Program Files (x86)")

    unique_roots: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        normalized = os.path.normcase(os.path.abspath(str(root)))
        if normalized in seen or not root.is_dir():
            continue
        seen.add(normalized)
        unique_roots.append(root)
    return unique_roots


def _find_candidates_in_root(root: Path) -> set[Path]:
    if is_starccm_executable(root):
        return {root}
    if not root.is_dir():
        return set()

    candidates: set[Path] = set()
    for pattern in _SEARCH_PATTERNS:
        try:
            matches = root.glob(pattern)
            candidates.update(path for path in matches if is_starccm_executable(path))
        except OSError:
            continue
    return candidates


def _starccm_candidate_sort_key(path: Path) -> tuple[tuple[int, ...], int, str]:
    relevant_parts = path.parts
    for index, part in enumerate(path.parts):
        normalized_part = re.sub(r"[^a-z0-9]", "", part.lower())
        if "starccm" in normalized_part:
            relevant_parts = path.parts[index:]
            break
    version_numbers = tuple(
        int(value)
        for value in re.findall(r"\d+", os.path.join(*relevant_parts))
    )
    try:
        modified_time_ns = path.stat().st_mtime_ns
    except OSError:
        modified_time_ns = 0
    return version_numbers, modified_time_ns, os.path.normcase(str(path))


def _fixed_windows_drives() -> list[Path]:
    if os.name != "nt":
        return []
    try:
        drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
        get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
    except (AttributeError, OSError):
        return []

    fixed_drives: list[Path] = []
    for index in range(26):
        if not drive_mask & (1 << index):
            continue
        drive = f"{chr(ord('A') + index)}:\\"
        if get_drive_type(drive) == 3:
            fixed_drives.append(Path(drive))
    return fixed_drives
