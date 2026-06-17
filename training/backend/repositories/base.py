from __future__ import annotations

from .._compat import slots_dataclass


@slots_dataclass
class RepositoryBase:
    session_factory: object
