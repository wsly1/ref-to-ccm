from __future__ import annotations

import json
from pathlib import Path

from refprop_to_ccm import gui
from refprop_to_ccm.starccm_locator import (
    choose_startup_starccm_path,
    find_starccm_executable,
    manual_starccm_path_from_config,
)


def _create_starccm_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    return path


def test_saved_valid_path_has_priority_over_auto_discovery(tmp_path: Path) -> None:
    saved = _create_starccm_executable(
        tmp_path / "saved" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )
    discovered = _create_starccm_executable(
        tmp_path / "STAR-CCM_202602" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )

    selected = choose_startup_starccm_path(str(saved), discovered)

    assert selected == str(saved)


def test_stale_saved_path_is_replaced_by_auto_discovery(tmp_path: Path) -> None:
    stale = tmp_path / "removed" / "starccm+.exe"
    discovered = _create_starccm_executable(
        tmp_path / "STAR-CCM_202602" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )

    selected = choose_startup_starccm_path(str(stale), discovered)

    assert selected == str(discovered)


def test_auto_discovery_prefers_explicit_environment_path(tmp_path: Path) -> None:
    environment_exe = _create_starccm_executable(
        tmp_path / "environment" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )
    scanned_exe = _create_starccm_executable(
        tmp_path / "Program Files" / "STAR-CCM_202602" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )

    found = find_starccm_executable(
        search_roots=[tmp_path / "Program Files"],
        environment={"STARCCM_EXE": str(environment_exe)},
    )

    assert found == environment_exe
    assert found != scanned_exe


def test_auto_discovery_selects_newest_installed_version(tmp_path: Path) -> None:
    program_files = tmp_path / "Program Files"
    _create_starccm_executable(
        program_files
        / "STAR-CCM_202401"
        / "starccm_2024"
        / "19.01.001"
        / "star"
        / "lib"
        / "win64"
        / "lib"
        / "starccm+.exe"
    )
    newest = _create_starccm_executable(
        program_files
        / "STAR-CCM_202602"
        / "starccm_2026"
        / "21.02.007"
        / "star"
        / "lib"
        / "win64"
        / "lib"
        / "starccm+.exe"
    )

    found = find_starccm_executable(
        search_roots=[program_files],
        environment={},
    )

    assert found == newest


def test_version_selection_ignores_program_files_x86_number(tmp_path: Path) -> None:
    older = _create_starccm_executable(
        tmp_path
        / "Program Files"
        / "STAR-CCM_202501"
        / "star"
        / "lib"
        / "win64"
        / "lib"
        / "starccm+.exe"
    )
    newer = _create_starccm_executable(
        tmp_path
        / "Program Files (x86)"
        / "STAR-CCM_202602"
        / "star"
        / "lib"
        / "win64"
        / "lib"
        / "starccm+.exe"
    )

    found = find_starccm_executable(
        search_roots=[
            tmp_path / "Program Files",
            tmp_path / "Program Files (x86)",
        ],
        environment={},
    )

    assert found == newer
    assert found != older


def test_manual_config_path_is_detected_for_auto_config_update() -> None:
    config = {
        "fields": {
            "fluid_name": "R454C",
            "starccm_exe": r"D:\Siemens\STAR-CCM+\starccm+.exe",
        }
    }

    assert manual_starccm_path_from_config(config) == r"D:\Siemens\STAR-CCM+\starccm+.exe"


def test_manual_config_without_starccm_path_does_not_override_auto_config() -> None:
    assert manual_starccm_path_from_config({"fields": {"fluid_name": "R454C"}}) is None


def test_gui_shares_and_auto_saves_starccm_path_across_pages(
    tmp_path: Path,
    monkeypatch,
) -> None:
    automatic_config = tmp_path / "automatic_config.json"
    detected = _create_starccm_executable(
        tmp_path / "STAR-CCM_202602" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
    )
    monkeypatch.setattr(gui, "CONFIG_FILE", automatic_config)
    monkeypatch.setattr(
        gui,
        "find_starccm_executable",
        lambda: detected,
        raising=False,
    )

    app = gui.RefpropToCcmApp()
    app.withdraw()
    try:
        assert app.vars["starccm_exe"] is app.report_starccm_exe
        assert app.star_apply_vars["starccm_exe"] is app.report_starccm_exe
        assert app.report_starccm_exe.get() == str(detected)

        selected = _create_starccm_executable(
            tmp_path / "selected" / "star" / "lib" / "win64" / "lib" / "starccm+.exe"
        )
        app.vars["starccm_exe"].set(str(selected))
        app.update_idletasks()

        saved = json.loads(automatic_config.read_text(encoding="utf-8"))
        assert saved["starccm_exe"] == str(selected)
        assert app.star_apply_vars["starccm_exe"].get() == str(selected)

        manual = tmp_path / "manual" / "starccm+.exe"
        app._apply_gui_state({"fields": {"starccm_exe": str(manual)}})
        app.update_idletasks()

        saved = json.loads(automatic_config.read_text(encoding="utf-8"))
        assert app.report_starccm_exe.get() == str(manual)
        assert app.star_apply_vars["starccm_exe"].get() == str(manual)
        assert saved["starccm_exe"] == str(manual)
    finally:
        app.destroy()
