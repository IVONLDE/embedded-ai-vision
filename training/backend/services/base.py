from __future__ import annotations

from .._compat import slots_dataclass


@slots_dataclass
class ServiceBase:
    paths: object
    session_factory: object
