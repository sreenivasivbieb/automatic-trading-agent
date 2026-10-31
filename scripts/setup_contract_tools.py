"""Install pinned, checksum-verified Linux x86_64 contract tools inside this project."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOUNDRY_URL = "https://github.com/foundry-rs/foundry/releases/download/v1.8.7/foundry_v1.8.7_linux_amd64.tar.gz"
FOUNDRY_SHA256 = "ba470eb718e779e4b0e3f1520b5284231b1bf98e9a39de07fb8f77ed70525bcf"
SOLC_URLS = [
    "https://raw.githubusercontent.com/ethereum/solc-bin/gh-pages/linux-amd64/solc-linux-amd64-v0.8.24+commit.e11b9ed9",
    "https://binaries.soliditylang.org/linux-amd64/solc-linux-amd64-v0.8.24+commit.e11b9ed9",
]
SOLC_SHA256 = "fb03a29a517452b9f12bcf459ef37d0a543765bb3bbc911e70a87d6a37c30d5f"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, path: Path, expected: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and digest(path) == expected:
        return
    for attempt in range(3):
        offset = path.stat().st_size if path.exists() else 0
        request = urllib.request.Request(
            url, headers={"Range": f"bytes={offset}-"} if offset else {}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                mode = "ab" if response.status == 206 and offset else "wb"
                with path.open(mode) as target:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        target.write(chunk)
            if digest(path) != expected:
                path.unlink()
                raise ValueError("Downloaded contract tool failed its pinned SHA-256 check")
            return
        except (OSError, ValueError) as exc:
            if getattr(exc, "code", None) == 416:
                path.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main() -> None:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise SystemExit(
            "This installer targets Linux x86_64. Use the official Foundry/Solidity builds for your platform and configure the compiler path."
        )
    archive = ROOT / ".cache/foundry/foundry-v1.8.7.tar.gz"
    print(
        "Contract toolchain: pinned Foundry 1.8.7 + Solidity 0.8.24; first setup downloads about 133 MB into project-local paths.",
        flush=True,
    )
    download(FOUNDRY_URL, archive, FOUNDRY_SHA256)
    target = ROOT / ".tools/foundry"
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as bundle:
        for name in ["forge", "cast", "anvil", "chisel"]:
            member = bundle.getmember(name)
            if not member.isfile() or member.name != name:
                raise ValueError("Unexpected file in the verified tool archive")
            source = bundle.extractfile(member)
            if source is None:
                raise ValueError("Verified tool archive has no executable contents")
            with source, tempfile.NamedTemporaryFile(dir=target, delete=False) as installed:
                temporary = Path(installed.name)
                try:
                    shutil.copyfileobj(source, installed)
                    installed.flush()
                    temporary.chmod(0o755)
                    os.replace(temporary, target / name)
                finally:
                    temporary.unlink(missing_ok=True)
    solc = ROOT / ".tools/solc/solc-0.8.24"
    for index, url in enumerate(SOLC_URLS):
        try:
            download(url, solc, SOLC_SHA256)
            break
        except (OSError, ValueError):
            if index + 1 == len(SOLC_URLS):
                raise
            print("Compiler mirror unavailable; trying the next official mirror.", flush=True)
    solc.chmod(0o755)
    print("Verified toolchain ready. No global installation or shared compiler cache is used.")


if __name__ == "__main__":
    main()
