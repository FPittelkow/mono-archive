from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from mono_archive.manifest import load_manifest, new_manifest, save_manifest


MANIFEST_NAME = "manifest.yaml"


@dataclass(frozen=True)
class Project:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME


def reference_project_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "_reference" / "_MI-YYYY-AA"


def find_projects(base_dir: Path) -> list[Project]:
    projects: list[Project] = []
    if (base_dir / MANIFEST_NAME).exists():
        projects.append(Project(base_dir))

    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and (child / MANIFEST_NAME).exists():
            projects.append(Project(child))
    return projects


def create_project(base_dir: Path, project_id: str) -> Project:
    clean_id = project_id.strip()
    if not clean_id:
        raise ValueError("A project ID is required before a project can be created.")

    target = base_dir / clean_id
    if target.exists():
        raise FileExistsError(f"{target} already exists.")

    template = reference_project_dir()
    if template.exists():
        ignore = shutil.ignore_patterns(".DS_Store")
        shutil.copytree(template, target, ignore=ignore)
    else:
        target.mkdir(parents=True)

    manifest = new_manifest()
    manifest["id"] = clean_id
    save_manifest(target / MANIFEST_NAME, manifest)
    return Project(target)


def load_project_manifest(project: Project) -> dict:
    return load_manifest(project.manifest_path)


def save_project_manifest(project: Project, data: dict) -> None:
    save_manifest(project.manifest_path, data)
