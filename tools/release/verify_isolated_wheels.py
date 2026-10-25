"""Install every built distribution in a fresh virtual environment.

Run after ``prepare_wheelhouse.py``.  Atlas Richie wheels and their locked
third-party runtime dependencies are resolved only from local build artifacts, so
this check cannot accidentally use the editable workspace environment or an index.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


def discover_packages(repository: Path) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Read each workspace distribution's exact version and declared import roots.

    Do not scan dist/: it can contain obsolete packages and versions from older
    releases. A missing manifest or module declaration is a failed release gate.
    """
    manifest = tomllib.loads((repository / "pyproject.toml").read_text())
    packages = []
    for member in manifest["tool"]["uv"]["workspace"]["members"]:
        metadata = tomllib.loads((repository / member / "pyproject.toml").read_text())
        project = metadata["project"]
        modules = metadata["tool"]["uv"]["build-backend"]["module-name"]
        if isinstance(modules, str):
            modules = [modules]
        if not modules or not all(isinstance(module, str) for module in modules):
            raise ValueError(f"Invalid import roots for {member}")
        packages.append((f"{project['name']}=={project['version']}", tuple(modules)))
    if not packages:
        raise ValueError("Workspace contains no distributions to verify")
    return tuple(packages)


def run(*args: str, cwd: Path) -> None:
    subprocess.run(args, check=True, cwd=cwd)


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, default=repository / "dist")
    parser.add_argument(
        "--package",
        action="append",
        help="Recheck a changed workspace distribution by name; repeatable",
    )
    arguments = parser.parse_args()
    wheelhouse = arguments.wheel_dir.resolve()
    dependency_wheelhouse = wheelhouse / "wheelhouse"
    packages = discover_packages(repository)
    selected = packages
    if arguments.package:
        names = {package.split("==")[0] for package, _ in packages}
        unknown = set(arguments.package) - names
        if unknown:
            parser.error(
                f"Unknown workspace distributions: {', '.join(sorted(unknown))}"
            )
        selected = tuple(
            item for item in packages if item[0].split("==")[0] in arguments.package
        )
    with tempfile.TemporaryDirectory(prefix="atlas-richie-wheel-") as temporary:
        temporary_path = Path(temporary)
        constraints = temporary_path / "workspace-constraints.txt"
        constraints.write_text("".join(f"{package}\n" for package, _ in packages))
        for index, (package, modules) in enumerate(selected, start=1):
            print(f"[{index}/{len(selected)}] Isolated wheel: {package}", flush=True)
            with tempfile.TemporaryDirectory(dir=temporary, prefix="package-") as check:
                working_directory = Path(check)
                environment = working_directory / "venv"
                run(
                    sys.executable,
                    "-m",
                    "venv",
                    str(environment),
                    cwd=working_directory,
                )
                python = environment / "bin" / "python"
                run(
                    str(python),
                    "-I",
                    "-m",
                    "pip",
                    "--isolated",
                    "install",
                    "--no-cache-dir",
                    "--no-index",
                    "--no-compile",
                    "--find-links",
                    str(wheelhouse),
                    "--find-links",
                    str(dependency_wheelhouse),
                    "--constraint",
                    str(constraints),
                    package,
                    cwd=working_directory,
                )
                run(
                    str(python),
                    "-I",
                    "-m",
                    "pip",
                    "--isolated",
                    "check",
                    cwd=working_directory,
                )
                name, version = package.split("==")
                run(
                    str(python),
                    "-I",
                    "-c",
                    "import importlib, importlib.metadata, pathlib, sys; "
                    f"assert importlib.metadata.version({name!r}) == {version!r}; "
                    f"modules = [importlib.import_module(name) for name in {modules!r}]; "
                    "assert all(module.__file__ and pathlib.Path(module.__file__).resolve()"
                    ".is_relative_to(pathlib.Path(sys.prefix).resolve()) for module in modules); "
                    "print(', '.join(module.__name__ for module in modules))",
                    cwd=working_directory,
                )
    print(f"Isolated wheel verification passed: {len(selected)} distributions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
