from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static, TextArea

from mono_archive.manifest import (
    FIELD_SPECS,
    FieldSpec,
    get_value,
    missing_required_fields,
    new_manifest,
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


class StartScreen(Screen):
    CSS = """
    StartScreen {
        align: center middle;
    }

    #start-panel {
        width: 72;
        height: auto;
        border: solid $accent;
        padding: 1 2;
    }

    .start-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .start-row {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        app = self.app
        assert isinstance(app, MonoArchiveApp)
        project_options = [(project.root.name, str(project.root)) for project in app.projects]

        with Container(id="start-panel"):
            yield Label("mono archive", classes="start-title")
            yield Static(f"Working directory: {app.base_dir}")
            yield Label("New project ID")
            yield Input(placeholder="MI-YYYY-AA", id="new-project-id")
            yield Button("Create project", id="create-project", variant="primary")
            yield Label("Load existing project", classes="start-row")
            yield Select(project_options, prompt="Choose project", id="project-select")
            yield Button("Load project", id="load-project")
            if not project_options:
                yield Static("No manifest.yaml found in this directory or direct children.")

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
            app.open_project(project)
            return

        if event.button.id == "load-project":
            selected = self.query_one("#project-select", Select).value
            if selected == Select.NULL:
                app.notify("Choose a project to load.", severity="warning")
                return
            app.open_project(Project(Path(str(selected))))


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

    #form {
        padding: 1 2;
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
        with ScrollableContainer(id="form"):
            for spec in FIELD_SPECS:
                with Horizontal(classes="field-row"):
                    yield Label(self._label_for(spec), id=self._label_id(spec), classes=self._label_classes(spec))
                    yield self._input_for(spec)
        with Horizontal(id="actions"):
            yield Button("Save", id="save", variant="primary")
            yield Button("Projects", id="back")
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
        self.query_one("#status", Static).update(self._status_text())

    def _update_custom_value(self, widget_id: str, value: str) -> None:
        path = self._path_from_custom_widget_id(widget_id)
        select = self.query_one(f"#{self._widget_id(path)}", Select)
        if select.value != "other":
            return
        set_value(self.manifest, path, value.strip() or "other")
        self._refresh_required_labels()
        self.query_one("#status", Static).update(self._status_text())

    def _refresh_required_labels(self) -> None:
        for spec in FIELD_SPECS:
            if not spec.required:
                continue
            label = self.query_one(f"#{self._label_id(spec)}", Label)
            label.update(self._label_for(spec))
            label.set_classes(self._label_classes(spec))

    def _status_text(self, saved: bool = False) -> str:
        missing = missing_required_fields(self.manifest)
        prefix = "Saved. " if saved else ""
        if missing:
            names = ", ".join(spec.label for spec in missing)
            return f"{prefix}Missing required fields: {names}"
        return f"{prefix}All required fields are filled."

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

    def on_mount(self) -> None:
        self.theme = "gruvbox"
        self.push_screen(StartScreen())

    def open_project(self, project: Project) -> None:
        manifest = load_project_manifest(project)
        self.projects = find_projects(self.base_dir)
        self.push_screen(ManifestEditorScreen(project, manifest))


def run(base_dir: Path | None = None) -> None:
    MonoArchiveApp(base_dir).run()
