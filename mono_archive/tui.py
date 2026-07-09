from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, Select, Static, TextArea

from mono_archive.manifest import (
    FIELD_SPECS,
    FieldSpec,
    get_value,
    missing_required_fields,
    set_value,
    text_to_value,
    value_to_text,
)
from mono_archive.project import (
    Project,
    create_project,
    find_projects,
    load_project_manifest,
    save_project_manifest,
)


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    manifest: dict[str, Any]
    filled_fields: int
    total_fields: int
    progress: float
    missing_required: tuple[FieldSpec, ...]

    @property
    def title(self) -> str:
        title = value_to_text("title", get_value(self.manifest, "title"))
        return title or self.project.root.name

    @property
    def project_id(self) -> str:
        project_id = value_to_text("id", get_value(self.manifest, "id"))
        return project_id or self.project.root.name

    @property
    def year(self) -> str:
        return value_to_text("year", get_value(self.manifest, "year")) or "-"

    @property
    def status(self) -> str:
        return value_to_text("status", get_value(self.manifest, "status")) or "missing"

    @property
    def documentation_level(self) -> str:
        return value_to_text("documentation_level", get_value(self.manifest, "documentation_level")) or "missing"

    @property
    def indicator(self) -> str:
        if self.missing_required:
            return "needs required"
        if self.progress >= 90:
            return "complete"
        if self.progress >= 60:
            return "in progress"
        return "starter"


SORT_OPTIONS = (
    ("Title", "title"),
    ("Project ID", "id"),
    ("Status", "status"),
    ("Progress", "progress"),
    ("Year", "year"),
)


def summarize_project(project: Project) -> ProjectSummary:
    manifest = load_project_manifest(project)
    filled = sum(1 for spec in FIELD_SPECS if not _is_empty_value(get_value(manifest, spec.path)))
    total = len(FIELD_SPECS)
    progress = (filled / total * 100) if total else 0
    return ProjectSummary(
        project=project,
        manifest=manifest,
        filled_fields=filled,
        total_fields=total,
        progress=progress,
        missing_required=tuple(missing_required_fields(manifest)),
    )


def manifest_progress(manifest: dict[str, Any]) -> tuple[int, int, float]:
    filled = sum(1 for spec in FIELD_SPECS if not _is_empty_value(get_value(manifest, spec.path)))
    total = len(FIELD_SPECS)
    progress = (filled / total * 100) if total else 0
    return filled, total, progress


def format_progress_bar(percent: float, width: int = 18) -> str:
    safe_percent = max(0, min(100, percent))
    filled = round(safe_percent / 100 * width)
    return f"[{'#' * filled}{'-' * (width - filled)}] {safe_percent:3.0f}%"


def reflection_lines(manifest: dict[str, Any]) -> list[str]:
    filled_specs = [spec for spec in FIELD_SPECS if not _is_empty_value(get_value(manifest, spec.path))]
    missing_required = missing_required_fields(manifest)
    empty_optional = [
        spec.label
        for spec in FIELD_SPECS
        if not spec.required and _is_empty_value(get_value(manifest, spec.path))
    ]
    documents = [
        f"{spec.label}: {value_to_text(spec.path, get_value(manifest, spec.path)) or 'missing'}"
        for spec in FIELD_SPECS
        if spec.path.startswith("documents.")
    ]

    lines = [
        f"Fields filled: {len(filled_specs)}/{len(FIELD_SPECS)}",
        f"Required missing: {', '.join(spec.label for spec in missing_required) if missing_required else 'none'}",
        f"Status: {value_to_text('status', get_value(manifest, 'status')) or 'missing'}",
        f"Documentation: {value_to_text('documentation_level', get_value(manifest, 'documentation_level')) or 'missing'}",
        "",
        "Documents",
        *documents,
        "",
        "Next fields",
        *empty_optional[:6],
    ]
    if len(empty_optional) > 6:
        lines.append(f"...and {len(empty_optional) - 6} more")
    return lines


def _is_empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, list):
        return len(value) == 0
    return False


class OverviewScreen(Screen):
    CSS = """
    OverviewScreen {
        layout: vertical;
    }

    #overview-heading {
        padding: 1 2;
        border-bottom: solid $accent;
    }

    #overview-body {
        height: 1fr;
    }

    #project-list {
        width: 2fr;
        min-width: 72;
        border-right: solid $accent;
    }

    #overview-toolbar {
        height: auto;
        padding: 1 1;
    }

    #sort-select {
        width: 24;
    }

    #directory-progress {
        width: 1fr;
        padding: 1 2;
    }

    #records-table {
        height: 1fr;
    }

    #project-details {
        width: 1fr;
        min-width: 38;
        padding: 1 2;
    }

    #detail-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #detail-progress {
        margin: 1 0;
    }

    #detail-reflection {
        height: 1fr;
    }

    #create-panel {
        height: auto;
        padding-top: 1;
        border-top: solid $accent;
    }

    #new-project-id {
        width: 1fr;
    }

    #detail-actions {
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("enter", "open_selected", "Edit"),
        ("f", "open_finder", "Finder"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.summaries: list[ProjectSummary] = []
        self.selected_project: Project | None = None
        self.sort_key = "title"

    def compose(self) -> ComposeResult:
        app = self.app
        assert isinstance(app, MonoArchiveApp)

        yield Header()
        yield Static(f"Mono Archive - {app.base_dir}", id="overview-heading")
        with Horizontal(id="overview-body"):
            with Vertical(id="project-list"):
                with Horizontal(id="overview-toolbar"):
                    yield Select(SORT_OPTIONS, value=self.sort_key, id="sort-select")
                    yield Button("Refresh", id="refresh")
                yield Static("", id="directory-progress")
                yield DataTable(id="records-table")
            with Vertical(id="project-details"):
                yield Static("No project selected", id="detail-title")
                yield Static("", id="detail-status")
                yield Static("", id="detail-progress")
                yield Static("", id="detail-reflection")
                with Horizontal(id="detail-actions"):
                    yield Button("Edit", id="load-project", variant="primary")
                    yield Button("Finder", id="open-finder")
                with Vertical(id="create-panel"):
                    yield Label("New project ID")
                    with Horizontal():
                        yield Input(placeholder="MI-YYYY-AA", id="new-project-id")
                        yield Button("Create", id="create-project")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#records-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        self.refresh_projects()

    def action_refresh(self) -> None:
        self.refresh_projects()

    def action_open_selected(self) -> None:
        self.open_selected_project()

    def action_open_finder(self) -> None:
        self.open_selected_in_finder()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app = self.app
        assert isinstance(app, MonoArchiveApp)

        if event.button.id == "create-project":
            project_id = self.query_one("#new-project-id", Input).value
            try:
                project = create_project(app.base_dir, project_id)
            except (ValueError, FileExistsError) as exc:
                app.notify(str(exc), severity="error")
                return
            self.refresh_projects(selected=project)
            app.open_project(project)
            return

        if event.button.id == "load-project":
            self.open_selected_project()
        elif event.button.id == "refresh":
            self.refresh_projects()
        elif event.button.id == "open-finder":
            self.open_selected_in_finder()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "sort-select" or event.value == Select.NULL:
            return
        self.sort_key = str(event.value)
        self.refresh_projects(selected=self.selected_project)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        project = self._project_from_row_key(event.row_key.value)
        if project is not None:
            self.selected_project = project
            self.update_details()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        project = self._project_from_row_key(event.row_key.value)
        if project is not None:
            self.selected_project = project
            self.update_details()

    def refresh_projects(self, selected: Project | None = None) -> None:
        app = self.app
        assert isinstance(app, MonoArchiveApp)
        app.refresh_projects()
        self.summaries = sorted(
            (summarize_project(project) for project in app.projects),
            key=self._sort_value,
            reverse=self.sort_key == "progress",
        )
        table = self.query_one("#records-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Project", "Status", "Docs", "Progress", "Missing")

        for summary in self.summaries:
            missing = ", ".join(spec.label for spec in summary.missing_required) or "-"
            table.add_row(
                summary.title,
                f"{summary.indicator} / {summary.status}",
                summary.documentation_level,
                format_progress_bar(summary.progress, width=12),
                missing,
                key=str(summary.project.root),
            )

        self.selected_project = selected or self.selected_project
        if self.selected_project not in [summary.project for summary in self.summaries]:
            self.selected_project = self.summaries[0].project if self.summaries else None
        self.update_directory_progress()
        self.update_details()

    def update_directory_progress(self) -> None:
        if not self.summaries:
            text = "No manifest.yaml found in this directory or its direct children."
        else:
            average = sum(summary.progress for summary in self.summaries) / len(self.summaries)
            ready = sum(1 for summary in self.summaries if not summary.missing_required)
            text = (
                f"Directory progress {format_progress_bar(average)}  "
                f"{ready}/{len(self.summaries)} records have all required fields."
            )
        self.query_one("#directory-progress", Static).update(text)

    def update_details(self) -> None:
        summary = self._selected_summary()
        if summary is None:
            self.query_one("#detail-title", Static).update("No project selected")
            self.query_one("#detail-status", Static).update("")
            self.query_one("#detail-progress", Static).update("")
            self.query_one("#detail-reflection", Static).update("Create a project to begin.")
            return

        self.query_one("#detail-title", Static).update(f"{summary.project_id} - {summary.title}")
        self.query_one("#detail-status", Static).update(
            f"{summary.indicator}\nStatus: {summary.status}\nYear: {summary.year}\nPath: {summary.project.root}"
        )
        self.query_one("#detail-progress", Static).update(format_progress_bar(summary.progress))
        self.query_one("#detail-reflection", Static).update("\n".join(reflection_lines(summary.manifest)))

    def open_selected_project(self) -> None:
        app = self.app
        assert isinstance(app, MonoArchiveApp)
        summary = self._selected_summary()
        if summary is None:
            app.notify("Choose a project to edit.", severity="warning")
            return
        app.open_project(summary.project)

    def open_selected_in_finder(self) -> None:
        app = self.app
        assert isinstance(app, MonoArchiveApp)
        summary = self._selected_summary()
        if summary is None:
            app.notify("Choose a project to open in Finder.", severity="warning")
            return
        try:
            subprocess.Popen(["open", str(summary.project.root)])
        except OSError as exc:
            app.notify(f"Could not open Finder: {exc}", severity="error")

    def _selected_summary(self) -> ProjectSummary | None:
        if self.selected_project is None:
            return None
        return next((summary for summary in self.summaries if summary.project == self.selected_project), None)

    def _project_from_row_key(self, row_key: object) -> Project | None:
        path = str(row_key)
        return next((summary.project for summary in self.summaries if str(summary.project.root) == path), None)

    def _sort_value(self, summary: ProjectSummary) -> str | float:
        if self.sort_key == "progress":
            return summary.progress
        if self.sort_key == "status":
            return summary.status
        if self.sort_key == "id":
            return summary.project_id
        if self.sort_key == "year":
            return summary.year
        return summary.title.lower()


class ManifestEditorScreen(Screen):
    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "back", "Projects"),
    ]

    CSS = """
    ManifestEditorScreen {
        layout: vertical;
    }

    #editor-heading {
        padding: 1 2;
        border-bottom: solid $accent;
    }

    #editor-body {
        height: 1fr;
    }

    #form {
        width: 2fr;
        padding: 1 2;
    }

    #editor-side {
        width: 42;
        padding: 1 2;
        border-left: solid $accent;
    }

    #editor-progress {
        margin: 1 0;
    }

    #editor-reflection {
        height: 1fr;
    }

    .field-row {
        height: auto;
        margin-bottom: 1;
    }

    .field-label {
        width: 28;
        padding-top: 1;
    }

    .required-missing {
        color: $error;
        text-style: bold;
    }

    .field-input {
        width: 1fr;
    }

    .choice-stack {
        width: 1fr;
        height: auto;
    }

    .custom-choice {
        width: 1fr;
        margin-top: 1;
    }

    .field-textarea {
        width: 1fr;
        height: 5;
    }

    #actions {
        height: auto;
        padding: 1 2;
        border-top: solid $accent;
    }

    #status {
        width: 1fr;
        padding-left: 2;
    }
    """

    def __init__(self, project: Project, manifest: dict[str, Any]) -> None:
        super().__init__()
        self.project = project
        self.manifest = manifest

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Editing {self.project.manifest_path}", id="editor-heading")
        with Horizontal(id="editor-body"):
            with ScrollableContainer(id="form"):
                for spec in FIELD_SPECS:
                    with Horizontal(classes="field-row"):
                        yield Label(self._label_for(spec), id=self._label_id(spec), classes=self._label_classes(spec))
                        yield self._input_for(spec)
            with Vertical(id="editor-side"):
                yield Static("Project progress", id="editor-side-title")
                yield Static(self._progress_text(), id="editor-progress")
                yield Static(self._reflection_text(), id="editor-reflection")
        with Horizontal(id="actions"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Projects", id="back")
            yield Button("Finder", id="open-finder")
            yield Static(self._status_text(), id="status")
        yield Footer()

    def action_save(self) -> None:
        self.save()

    def action_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.save()
        elif event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "open-finder":
            self.open_in_finder()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("custom-"):
            self._update_custom_value(event.input.id, event.value)
            return
        self._update_value(event.input.id, event.value)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self._update_value(event.text_area.id, event.text_area.text)

    def on_select_changed(self, event: Select.Changed) -> None:
        value = "" if event.value == Select.NULL else str(event.value)
        if event.select.id is not None:
            path = self._path_from_widget_id(event.select.id)
            spec = self._spec_for_path(path)
            if spec is not None and self._allows_custom_choice(spec):
                custom = self.query_one(f"#{self._custom_widget_id(path)}", Input)
                custom.display = value == "other"
                if value == "other":
                    value = custom.value.strip() or "other"
        self._update_value(event.select.id, value)

    def save(self) -> None:
        save_project_manifest(self.project, self.manifest)
        app = self.app
        if isinstance(app, MonoArchiveApp):
            app.refresh_overview(self.project)
        self.query_one("#status", Static).update(self._status_text(saved=True))
        self.app.notify(f"Saved {self.project.manifest_path}")

    def _input_for(self, spec: FieldSpec):
        value = value_to_text(spec.path, get_value(self.manifest, spec.path))
        widget_id = self._widget_id(spec.path)
        if spec.choices:
            options = [(choice, choice) for choice in spec.choices]
            if self._allows_custom_choice(spec) and value and value not in spec.choices:
                selected = "other"
                custom_value = value
                custom_visible = True
            else:
                selected = value if value in spec.choices else Select.NULL
                custom_value = ""
                custom_visible = selected == "other"
            if not self._allows_custom_choice(spec):
                return Select(options, prompt="Select", value=selected, id=widget_id, classes="field-input")
            custom = Input(
                value=custom_value,
                placeholder=f"Enter custom {spec.label.lower()}",
                id=self._custom_widget_id(spec.path),
                classes="custom-choice",
            )
            custom.display = custom_visible
            return Vertical(
                Select(options, prompt="Select", value=selected, id=widget_id, classes="field-input"),
                custom,
                classes="choice-stack",
            )
        if spec.multiline:
            return TextArea(value, id=widget_id, classes="field-textarea")
        return Input(value=value, placeholder=spec.placeholder, id=widget_id, classes="field-input")

    def _update_value(self, widget_id: str | None, value: str) -> None:
        if widget_id is None:
            return
        path = self._path_from_widget_id(widget_id)
        set_value(self.manifest, path, text_to_value(path, value))
        self._refresh_required_labels()
        self._refresh_reflection()
        self.query_one("#status", Static).update(self._status_text())

    def _update_custom_value(self, widget_id: str, value: str) -> None:
        path = self._path_from_custom_widget_id(widget_id)
        select = self.query_one(f"#{self._widget_id(path)}", Select)
        if select.value != "other":
            return
        set_value(self.manifest, path, value.strip() or "other")
        self._refresh_required_labels()
        self._refresh_reflection()
        self.query_one("#status", Static).update(self._status_text())

    def _refresh_required_labels(self) -> None:
        for spec in FIELD_SPECS:
            if not spec.required:
                continue
            label = self.query_one(f"#{self._label_id(spec)}", Label)
            label.update(self._label_for(spec))
            label.set_classes(self._label_classes(spec))

    def _refresh_reflection(self) -> None:
        self.query_one("#editor-progress", Static).update(self._progress_text())
        self.query_one("#editor-reflection", Static).update(self._reflection_text())

    def _status_text(self, saved: bool = False) -> str:
        missing = missing_required_fields(self.manifest)
        prefix = "Saved. " if saved else ""
        if missing:
            names = ", ".join(spec.label for spec in missing)
            return f"{prefix}Missing required fields: {names}"
        return f"{prefix}All required fields are filled."

    def _progress_text(self) -> str:
        filled, total, progress = manifest_progress(self.manifest)
        return f"{format_progress_bar(progress)}\n{filled}/{total} fields filled"

    def _reflection_text(self) -> str:
        return "\n".join(reflection_lines(self.manifest))

    def open_in_finder(self) -> None:
        try:
            subprocess.Popen(["open", str(self.project.root)])
        except OSError as exc:
            self.app.notify(f"Could not open Finder: {exc}", severity="error")

    def _label_for(self, spec: FieldSpec) -> str:
        marker = "!" if spec.required and get_value(self.manifest, spec.path) in {"", None} else " "
        return f"[{marker}] {spec.label}"

    def _label_classes(self, spec: FieldSpec) -> str:
        classes = "field-label"
        if spec.required and get_value(self.manifest, spec.path) in {"", None}:
            classes += " required-missing"
        return classes

    @staticmethod
    def _widget_id(path: str) -> str:
        return "field-" + path.replace(".", "-")

    @staticmethod
    def _custom_widget_id(path: str) -> str:
        return "custom-" + path.replace(".", "-")

    @staticmethod
    def _label_id(spec: FieldSpec) -> str:
        return "label-" + spec.path.replace(".", "-")

    @staticmethod
    def _path_from_widget_id(widget_id: str) -> str:
        return widget_id.removeprefix("field-").replace("-", ".")

    @staticmethod
    def _path_from_custom_widget_id(widget_id: str) -> str:
        return widget_id.removeprefix("custom-").replace("-", ".")

    @staticmethod
    def _allows_custom_choice(spec: FieldSpec) -> bool:
        return "other" in spec.choices

    @staticmethod
    def _spec_for_path(path: str) -> FieldSpec | None:
        return next((spec for spec in FIELD_SPECS if spec.path == path), None)


class MonoArchiveApp(App):
    TITLE = "Mono Archive"
    CSS = """
    Screen {
        background: $surface;
    }
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__()
        self.base_dir = (base_dir or Path.cwd()).resolve()
        self.projects = find_projects(self.base_dir)
        self.overview_screen: OverviewScreen | None = None

    def on_mount(self) -> None:
        self.theme = "gruvbox"
        self.overview_screen = OverviewScreen()
        self.push_screen(self.overview_screen)

    def refresh_projects(self) -> None:
        self.projects = find_projects(self.base_dir)

    def refresh_overview(self, selected: Project | None = None) -> None:
        self.refresh_projects()
        if self.overview_screen is not None and self.overview_screen.is_mounted:
            self.overview_screen.refresh_projects(selected=selected)

    def open_project(self, project: Project) -> None:
        manifest = load_project_manifest(project)
        self.refresh_projects()
        self.push_screen(ManifestEditorScreen(project, manifest))


def run(base_dir: Path | None = None) -> None:
    MonoArchiveApp(base_dir).run()
