from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class TaskType(str, Enum):
    CLEANING = "cleaning"
    GENERATION = "generation"
    EVALUATION = "evaluation"


class AlgorithmCategory(str, Enum):
    CLEANING = "cleaning"
    GENERATION = "generation"
    EVALUATION = "evaluation"
