from __future__ import annotations

from ._compat import slots_dataclass

from .repositories import AlgorithmRepository, DatasetRepository, LogRepository, SettingsRepository, TaskRepository
from .services import (
    AlgorithmService,
    CleaningService,
    DatasetService,
    EvaluationService,
    GenerationService,
    SettingsService,
    TrainingService,
    ExportService,
    EdgeService,
)
from .storage.paths import BackendPaths
from .task_manager import TaskManager


@slots_dataclass
class BackendServiceFacade:
    paths: BackendPaths
    session_factory: object
    dataset_repository: DatasetRepository
    task_repository: TaskRepository
    algorithm_repository: AlgorithmRepository
    settings_repository: SettingsRepository
    log_repository: LogRepository
    task_manager: TaskManager
    dataset_service: DatasetService
    cleaning_service: CleaningService
    generation_service: GenerationService
    evaluation_service: EvaluationService
    algorithm_service: AlgorithmService
    settings_service: SettingsService
    training_service: TrainingService
    export_service: ExportService
    edge_service: EdgeService

    @classmethod
    def build(cls, *, paths: BackendPaths, session_factory):
        dataset_repository = DatasetRepository(session_factory)
        task_repository = TaskRepository(session_factory)
        algorithm_repository = AlgorithmRepository(session_factory)
        settings_repository = SettingsRepository(session_factory)
        log_repository = LogRepository(session_factory)
        task_manager = TaskManager(paths=paths, session_factory=session_factory, task_repository=task_repository, log_repository=log_repository)
        dataset_service = DatasetService(paths=paths, session_factory=session_factory, dataset_repository=dataset_repository, log_repository=log_repository)
        cleaning_service = CleaningService(
            paths=paths,
            session_factory=session_factory,
            task_manager=task_manager,
            task_repository=task_repository,
            algorithm_repository=algorithm_repository,
            dataset_repository=dataset_repository,
        )
        generation_service = GenerationService(
            paths=paths,
            session_factory=session_factory,
            task_manager=task_manager,
            task_repository=task_repository,
            algorithm_repository=algorithm_repository,
            dataset_repository=dataset_repository,
        )
        evaluation_service = EvaluationService(
            paths=paths,
            session_factory=session_factory,
            task_manager=task_manager,
            task_repository=task_repository,
            algorithm_repository=algorithm_repository,
            dataset_repository=dataset_repository,
        )
        training_service = TrainingService(
            paths=paths,
            session_factory=session_factory,
            task_manager=task_manager,
            task_repository=task_repository,
            algorithm_repository=algorithm_repository,
            dataset_repository=dataset_repository,
        )
        algorithm_service = AlgorithmService(paths=paths, session_factory=session_factory, algorithm_repository=algorithm_repository, log_repository=log_repository)
        settings_service = SettingsService(paths=paths, session_factory=session_factory, settings_repository=settings_repository, log_repository=log_repository)
        export_service = ExportService(paths=paths, session_factory=session_factory, algorithm_repository=algorithm_repository, log_repository=log_repository)
        edge_service = EdgeService(paths=paths, session_factory=session_factory, log_repository=log_repository)
        return cls(
            paths=paths,
            session_factory=session_factory,
            dataset_repository=dataset_repository,
            task_repository=task_repository,
            algorithm_repository=algorithm_repository,
            settings_repository=settings_repository,
            log_repository=log_repository,
            task_manager=task_manager,
            dataset_service=dataset_service,
            cleaning_service=cleaning_service,
            generation_service=generation_service,
            evaluation_service=evaluation_service,
            training_service=training_service,
            algorithm_service=algorithm_service,
            settings_service=settings_service,
        )
