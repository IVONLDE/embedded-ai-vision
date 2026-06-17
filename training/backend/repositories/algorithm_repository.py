from __future__ import annotations

from ..models import Algorithm, AlgorithmBinding, AlgorithmParameter
from .base import RepositoryBase


class AlgorithmRepository(RepositoryBase):
    def create_algorithm(self, session, **values) -> Algorithm:
        algorithm = Algorithm(**values)
        session.add(algorithm)
        session.flush()
        return algorithm

    def replace_parameters(self, session, algorithm_id: int, parameters: list[dict]) -> None:
        session.query(AlgorithmParameter).filter(AlgorithmParameter.algorithm_id == algorithm_id).delete()
        for index, parameter in enumerate(parameters):
            session.add(
                AlgorithmParameter(
                    algorithm_id=algorithm_id,
                    name=parameter["name"],
                    label=parameter.get("label", parameter["name"]),
                    type=parameter["type"],
                    required=parameter.get("required", False),
                    default_value=parameter.get("default_value"),
                    min_value=parameter.get("min_value"),
                    max_value=parameter.get("max_value"),
                    options_json=parameter.get("options", []),
                    description=parameter.get("description", ""),
                    order_index=index,
                )
            )
        session.flush()

    def get_algorithm(self, session, algorithm_id: int) -> Algorithm | None:
        return session.query(Algorithm).filter(Algorithm.id == algorithm_id).first()

    def get_algorithm_by_key(self, session, key: str) -> Algorithm | None:
        return session.query(Algorithm).filter(Algorithm.key == key).first()

    def list_algorithms(self, session, *, category: str = "", modality: str = "") -> list[Algorithm]:
        query = session.query(Algorithm)
        if category:
            query = query.filter(Algorithm.category == category)
        if modality:
            query = query.filter(Algorithm.modality.in_([modality, "multimodal"]))
        return query.order_by(Algorithm.created_at.desc(), Algorithm.id.desc()).all()

    def list_parameters(self, session, algorithm_id: int) -> list[AlgorithmParameter]:
        return (
            session.query(AlgorithmParameter)
            .filter(AlgorithmParameter.algorithm_id == algorithm_id)
            .order_by(AlgorithmParameter.order_index.asc(), AlgorithmParameter.id.asc())
            .all()
        )

    # ── 绑定管理 ──────────────────────────────────────────────

    def get_binding_for_training(self, session, training_algo_id: int) -> AlgorithmBinding | None:
        return (
            session.query(AlgorithmBinding)
            .filter(AlgorithmBinding.training_algorithm_id == training_algo_id)
            .first()
        )

    def get_all_bindings(self, session) -> list[AlgorithmBinding]:
        return session.query(AlgorithmBinding).order_by(AlgorithmBinding.id.asc()).all()

    def set_binding(self, session, training_algo_id: int, eval_algo_id: int) -> AlgorithmBinding:
        existing = self.get_binding_for_training(session, training_algo_id)
        if existing:
            existing.evaluation_algorithm_id = eval_algo_id
            session.flush()
            return existing
        binding = AlgorithmBinding(
            training_algorithm_id=training_algo_id,
            evaluation_algorithm_id=eval_algo_id,
        )
        session.add(binding)
        session.flush()
        return binding

    def delete_binding_for_training(self, session, training_algo_id: int) -> bool:
        count = (
            session.query(AlgorithmBinding)
            .filter(AlgorithmBinding.training_algorithm_id == training_algo_id)
            .delete()
        )
        session.flush()
        return count > 0

    def delete_bindings_for_algorithm(self, session, algo_id: int) -> int:
        count = (
            session.query(AlgorithmBinding)
            .filter(
                (AlgorithmBinding.training_algorithm_id == algo_id)
                | (AlgorithmBinding.evaluation_algorithm_id == algo_id)
            )
            .delete()
        )
        session.flush()
        return count
