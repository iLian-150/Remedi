"""Extract trusted APT packages into this project; never install host packages."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


REQUIRED = ("tesseract-ocr", "tesseract-ocr-chi-sim", "tesseract-ocr-eng", "tesseract-ocr-osd")
BASE_LIBRARIES = {"libc6", "libc-bin", "libgcc-s1", "libstdc++6"}


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, env={**os.environ, "LC_ALL": "C"}, text=True)


def planned_packages(output):
    if re.search(r"^Remv\s", output, re.MULTILINE):
        raise ValueError("APT proposed package removals; refusing the incompatible plan")
    packages = dict(re.findall(r"^Inst\s+(\S+)(?:\s+\[[^\]]+\])?\s+\((\S+)", output, re.MULTILINE))
    if any(name.split(":")[0] in BASE_LIBRARIES for name in packages):
        raise ValueError("OCR requires a different host C/C++ runtime; update the host separately")
    return packages


def candidate(package):
    match = re.search(r"^\s*Candidate:\s+(\S+)", run("apt-cache", "policy", package), re.MULTILINE)
    if not match or match[1] == "(none)":
        raise RuntimeError(f"No APT candidate for {package}")
    return match[1]


def install(root):
    architecture = run("dpkg", "--print-architecture").strip()
    multiarch = {"arm64": "aarch64-linux-gnu", "amd64": "x86_64-linux-gnu"}.get(architecture)
    if multiarch is None:
        raise RuntimeError("This installer supports Ubuntu/Debian ARM64 and AMD64")
    plan = run("apt-get", "--simulate", "--no-install-recommends", "install", *REQUIRED)
    packages = planned_packages(plan)
    for name in REQUIRED:
        if name not in packages:
            packages[name] = candidate(name)
    root.mkdir(parents=True, exist_ok=True)
    active = root / "ocr"
    if active.exists() and not active.is_symlink():
        raise RuntimeError("The active OCR path is not a symlink; refusing to replace it")
    stage = Path(tempfile.mkdtemp(prefix=".ocr-build-", dir=root))
    stage.chmod(0o755)
    downloads = stage / "packages"
    downloads.mkdir()
    print(f"Downloading {len(packages)} OCR packages into the project", flush=True)
    run("apt-get", "download", *(f"{name}={version}" for name, version in packages.items()), cwd=downloads)
    manifest = []
    for archive in sorted(downloads.glob("*.deb")):
        name = run("dpkg-deb", "--field", str(archive), "Package").strip()
        version = run("dpkg-deb", "--field", str(archive), "Version").strip()
        package_arch = run("dpkg-deb", "--field", str(archive), "Architecture").strip()
        expected = packages.get(name, packages.get(f"{name}:{architecture}"))
        if version != expected or package_arch not in {architecture, "all"}:
            raise RuntimeError("Downloaded package metadata differs from the APT plan")
        with archive.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        manifest.append({"package": name, "version": version, "architecture": package_arch, "sha256": digest})
        run("dpkg-deb", "--extract", str(archive), str(stage))
    if len(manifest) != len(packages):
        raise RuntimeError("Not all planned packages were downloaded")
    tessdata = list((stage / "usr/share").glob("tesseract-ocr/*/tessdata/chi_sim.traineddata"))
    if len(tessdata) != 1:
        raise RuntimeError("Chinese OCR language data was not found")
    relative_data = tessdata[0].parent.relative_to(stage).as_posix()
    (stage / "bin").mkdir()
    wrapper = stage / "bin/tesseract"
    wrapper.write_text(
        '#!/bin/sh\nset -eu\n'
        'ocr_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)\n'
        f'export LD_LIBRARY_PATH="$ocr_root/usr/lib/{multiarch}:$ocr_root/usr/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"\n'
        f'export TESSDATA_PREFIX="$ocr_root/{relative_data}"\n'
        'exec "$ocr_root/usr/bin/tesseract" "$@"\n', encoding="utf-8",
    )
    wrapper.chmod(0o755)
    languages = run(str(wrapper), "--list-langs").splitlines()
    if not {"chi_sim", "eng"}.issubset(set(languages)):
        raise RuntimeError("OCR Chinese/English language verification failed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (stage / "manifest.json").write_text(json.dumps({"architecture": architecture, "packages": manifest}, indent=2))
    release = root / f"ocr-{architecture}-{stamp}"
    stage.rename(release)
    temporary_link = root / f".ocr-link-{stamp}"
    temporary_link.symlink_to(release.name, target_is_directory=True)
    temporary_link.replace(active)
    print(f"OCR ready: {active / 'bin/tesseract'} (chi_sim, eng; previous versions preserved)")


def main():
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo / "runtime")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_relative_to(repo) or root == repo:
        parser.error("OCR runtime must be inside the project")
    install(root)


if __name__ == "__main__":
    main()
