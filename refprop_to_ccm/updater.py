from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GITHUB_OWNER = "wsly1"
GITHUB_REPO = "ref-to-ccm"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_LATEST_RELEASE_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_RELEASE_DOWNLOAD_BASE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download"
GITHUB_LATEST_DOWNLOAD_BASE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest/download"
PREFERRED_ASSET_NAME = "refprop-to-ccm.exe"
USER_AGENT = "refprop-to-ccm-updater"


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    name: str
    html_url: str
    published_at: str
    asset_name: str
    asset_download_url: str


def check_for_update(current_version: str) -> ReleaseInfo | None:
    try:
        release = _release_from_public_pages()
    except UpdateError:
        payload = _request_json(GITHUB_LATEST_RELEASE_API)
        release = _release_from_payload(payload)
    if not _is_newer_version(release.tag_name, current_version):
        return None
    return release


def download_release_asset(release: ReleaseInfo, destination_dir: Path | None = None) -> Path:
    directory = destination_dir or Path(tempfile.gettempdir()) / "refprop-to-ccm-updates"
    directory.mkdir(parents=True, exist_ok=True)
    safe_tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", release.tag_name.strip() or "latest")
    target = directory / f"refprop-to-ccm-{safe_tag}.exe"
    request = urllib.request.Request(
        release.asset_download_url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
    except Exception as exc:
        try:
            target.unlink()
        except OSError:
            pass
        raise UpdateError(f"下载更新失败: {exc}") from exc
    if target.stat().st_size <= 0:
        target.unlink(missing_ok=True)
        raise UpdateError("下载更新失败: release 资源为空。")
    return target


def current_executable_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def install_update_and_restart(downloaded_exe: Path, current_exe: Path) -> None:
    if os.name != "nt":
        raise UpdateError("自动替换当前程序只支持 Windows EXE。")
    if not downloaded_exe.exists():
        raise UpdateError(f"更新文件不存在: {downloaded_exe}")
    if not current_exe.exists():
        raise UpdateError(f"当前程序不存在: {current_exe}")

    script_path = downloaded_exe.with_suffix(".bat")
    script_path.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "SRC={downloaded_exe}"',
                f'set "DST={current_exe}"',
                "timeout /t 2 /nobreak >nul",
                ":retry",
                'copy /Y "%SRC%" "%DST%" >nul',
                "if errorlevel 1 (",
                "  timeout /t 1 /nobreak >nul",
                "  goto retry",
                ")",
                'start "" "%DST%"',
                'del "%SRC%" >nul 2>nul',
                'del "%~f0" >nul 2>nul',
            ]
        ),
        encoding="utf-8",
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        cwd=str(current_exe.parent),
        creationflags=creationflags,
    )


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = _read_error_detail(exc)
        raise UpdateError(f"检查更新失败: GitHub 返回 HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise UpdateError(f"检查更新失败: {exc}") from exc


def _release_from_public_pages() -> ReleaseInfo:
    tag_name = _tag_from_latest_redirect()
    if not tag_name or not _url_exists(f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{urllib.parse.quote(tag_name, safe='')}"):
        tag_name = _tag_from_releases_page()
    asset_name = PREFERRED_ASSET_NAME
    tag_asset_url = f"{GITHUB_RELEASE_DOWNLOAD_BASE}/{urllib.parse.quote(tag_name, safe='')}/{asset_name}"
    latest_asset_url = f"{GITHUB_LATEST_DOWNLOAD_BASE}/{asset_name}"
    asset_url = tag_asset_url if _url_exists(tag_asset_url) else latest_asset_url
    return ReleaseInfo(
        tag_name=tag_name,
        name=tag_name,
        html_url=f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{urllib.parse.quote(tag_name, safe='')}",
        published_at="",
        asset_name=asset_name,
        asset_download_url=asset_url,
    )


def _tag_from_latest_redirect() -> str | None:
    opener = urllib.request.build_opener(_NoRedirectHandler)
    request = urllib.request.Request(
        GITHUB_LATEST_RELEASE_PAGE,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        opener.open(request, timeout=20)
        return None
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise UpdateError(f"检查更新失败: 无法访问 GitHub latest release 页面: HTTP {exc.code}") from exc
        final_url = exc.headers.get("Location") or ""
    except Exception as exc:
        raise UpdateError(f"检查更新失败: 无法访问 GitHub latest release 页面: {exc}") from exc

    marker = "/releases/tag/"
    if marker not in final_url:
        return None
    tag_name = urllib.parse.unquote(final_url.rsplit(marker, 1)[1].split("?", 1)[0].split("#", 1)[0])
    if not tag_name:
        return None
    return tag_name


def _tag_from_releases_page() -> str:
    request = urllib.request.Request(
        GITHUB_RELEASES_PAGE,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            html = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise UpdateError(f"检查更新失败: 无法访问 GitHub releases 页面: {exc}") from exc
    pattern = re.compile(rf"/{re.escape(GITHUB_OWNER)}/{re.escape(GITHUB_REPO)}/releases/tag/([^\"?#]+)")
    match = pattern.search(html)
    if not match:
        raise UpdateError("检查更新失败: 无法从 GitHub releases 页面解析版本。")
    return urllib.parse.unquote(match.group(1))


def _url_exists(url: str) -> bool:
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return str(exc)
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    return str(exc)


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        raise UpdateError("检查更新失败: GitHub release 缺少 tag_name。")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("检查更新失败: GitHub release assets 格式无效。")

    selected_asset: dict[str, Any] | None = None
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("name") or "").lower() == PREFERRED_ASSET_NAME:
            selected_asset = asset
            break
    if selected_asset is None:
        for asset in assets:
            if isinstance(asset, dict) and str(asset.get("name") or "").lower().endswith(".exe"):
                selected_asset = asset
                break
    if selected_asset is None:
        raise UpdateError(f"最新 release 未找到 EXE 资源，请上传 {PREFERRED_ASSET_NAME}。")

    asset_name = str(selected_asset.get("name") or "").strip()
    download_url = str(selected_asset.get("browser_download_url") or "").strip()
    if not asset_name or not download_url:
        raise UpdateError("检查更新失败: GitHub release 资源缺少下载地址。")

    return ReleaseInfo(
        tag_name=tag_name,
        name=str(payload.get("name") or tag_name),
        html_url=str(payload.get("html_url") or ""),
        published_at=str(payload.get("published_at") or ""),
        asset_name=asset_name,
        asset_download_url=download_url,
    )


def _is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = _version_parts(candidate)
    current_parts = _version_parts(current)
    if not candidate_parts or not current_parts:
        return candidate.strip().lower() != current.strip().lower()
    width = max(len(candidate_parts), len(current_parts))
    candidate_parts = candidate_parts + (0,) * (width - len(candidate_parts))
    current_parts = current_parts + (0,) * (width - len(current_parts))
    return candidate_parts > current_parts


def _version_parts(value: str) -> tuple[int, ...]:
    text = value.strip().lower()
    if text.startswith("refs/tags/"):
        text = text[len("refs/tags/") :]
    if text.startswith("v"):
        text = text[1:]
    match = re.match(r"^(\d+(?:\.\d+)*)", text)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))
