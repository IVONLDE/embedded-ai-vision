from __future__ import annotations

from dataclasses import field
from .._compat import slots_dataclass
from pathlib import Path


@slots_dataclass
class BackendPaths:
    root: Path
    data_dir: Path = field(init=False)
    datasets_dir: Path = field(init=False)
    tasks_dir: Path = field(init=False)
    reports_dir: Path = field(init=False)
    plugins_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    settings_dir: Path = field(init=False)
    database_path: Path = field(init=False)

    def __post_init__(self):
        self.root = Path(self.root)
        self.data_dir = self.root / "data"
        self.datasets_dir = self.data_dir / "datasets"
        self.tasks_dir = self.data_dir / "tasks"
        self.reports_dir = self.data_dir / "reports"
        self.plugins_dir = self.root / "plugins"
        self.logs_dir = self.root / "logs"
        self.settings_dir = self.root / "settings"
        self.database_path = self.data_dir / "isg_backend.db"
        for path in [
            self.root,
            self.data_dir,
            self.datasets_dir,
            self.tasks_dir,
            self.reports_dir,
            self.plugins_dir,
            self.logs_dir,
            self.settings_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)
