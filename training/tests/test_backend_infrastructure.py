from pathlib import Path


def test_backend_package_exports_infrastructure_entrypoints():
    from backend import (
        BackendPaths,
        TaskStatus,
        create_backend_engine,
        initialize_backend_database,
    )

    assert BackendPaths is not None
    assert TaskStatus is not None
    assert callable(create_backend_engine)
    assert callable(initialize_backend_database)


def test_task_status_contract_matches_architecture():
    from backend import TaskStatus

    assert [status.value for status in TaskStatus] == [
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]


def test_backend_database_initialization_creates_schema_and_storage_dirs(tmp_path):
    from sqlalchemy import inspect

    from backend import BackendPaths, create_backend_engine, initialize_backend_database

    root = tmp_path / "backend-root"
    paths = BackendPaths(root)
    engine = create_backend_engine(paths.database_path)

    initialize_backend_database(engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    expected_tables = {
        "datasets",
        "samples",
        "dataset_statistics",
        "algorithms",
        "algorithm_parameters",
        "tasks",
        "task_logs",
        "cleaning_suggestions",
        "generation_outputs",
        "evaluation_scenarios",
        "evaluation_results",
        "app_settings",
        "operation_logs",
    }

    assert expected_tables.issubset(table_names)
    assert paths.datasets_dir.is_dir()
    assert paths.tasks_dir.is_dir()
    assert paths.reports_dir.is_dir()
    assert paths.plugins_dir.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.database_path.name == "isg_backend.db"


def test_backend_service_facade_builds_services_and_task_manager_contract(tmp_path):
    from backend import BackendPaths, BackendServiceFacade, create_backend_engine, create_session_factory, initialize_backend_database

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)

    facade = BackendServiceFacade.build(paths=paths, session_factory=session_factory)

    assert facade.dataset_service is not None
    assert facade.algorithm_service is not None
    assert hasattr(facade.task_manager, "start")
    assert hasattr(facade.task_manager, "cancel")
    assert hasattr(facade.task_manager, "mark_interrupted_tasks")
    assert hasattr(facade.task_manager, "get_running_task_ids")


def test_plugin_runner_validates_and_executes_python_script(tmp_path):
    from backend.plugins import PluginRunner

    plugin_file = tmp_path / "runner_demo.py"
    plugin_file.write_text(
        "def run(payload, context):\n"
        "    context.log('info', 'runner-demo', payload)\n"
        "    return {'ok': True, 'echo': payload}\n",
        encoding="utf-8",
    )

    class DummyContext:
        def __init__(self):
            self.logs = []

        def set_progress(self, progress: float, message: str = "") -> None:
            return None

        def log(self, level: str, message: str, payload=None) -> None:
            self.logs.append((level, message, payload))

        def is_cancel_requested(self) -> bool:
            return False

    runner = PluginRunner()
    validated = runner.validate_entry(script_path=str(plugin_file), callable_name="run")
    context = DummyContext()
    result = runner.run({"hello": "world"}, context, script_path=str(plugin_file), callable_name="run")

    assert validated["ok"] is True
    assert validated["callable_name"] == "run"
    assert result["ok"] is True
    assert context.logs[0][1] == "runner-demo"
