from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func

from ..models import Dataset, DatasetStatistics, Sample
from .base import RepositoryBase


class DatasetRepository(RepositoryBase):
    def create_dataset(self, session, **values) -> Dataset:
        dataset = Dataset(**values)
        session.add(dataset)
        session.flush()
        return dataset

    def get_dataset(self, session, dataset_id: int, *, include_deleted: bool = False) -> Dataset | None:
        query = session.query(Dataset).filter(Dataset.id == dataset_id)
        if not include_deleted:
            query = query.filter(Dataset.is_deleted.is_(False))
        return query.first()

    def list_datasets(self, session, *, page: int, page_size: int, status: str = "", include_deleted: bool = False):
        query = session.query(Dataset)
        if not include_deleted:
            query = query.filter(Dataset.is_deleted.is_(False))
        if status:
            query = query.filter(Dataset.status == status)
        total = query.count()
        items = (
            query.order_by(Dataset.created_at.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return total, items

    def create_sample(self, session, **values) -> Sample:
        sample = Sample(**values)
        session.add(sample)
        session.flush()
        return sample

    def list_samples(self, session, *, dataset_id: int, page: int, page_size: int, status: str = ""):
        query = session.query(Sample).filter(Sample.dataset_id == dataset_id)
        if status:
            query = query.filter(Sample.status == status)
        total = query.count()
        items = (
            query.order_by(Sample.created_at.desc(), Sample.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return total, items

    def get_all_samples(self, session, dataset_id: int):
        return (
            session.query(Sample)
            .filter(Sample.dataset_id == dataset_id)
            .order_by(Sample.relative_path)
            .all()
        )

    def preview_samples(self, session, *, dataset_id: int, limit: int, status: str = ""):
        query = session.query(Sample).filter(Sample.dataset_id == dataset_id)
        if status:
            query = query.filter(Sample.status == status)
        total = query.count()
        items = query.order_by(Sample.created_at.desc(), Sample.id.desc()).limit(limit).all()
        return total, items

    def count_by_modality(self, session):
        rows = (
            session.query(Sample.modality, func.count(Sample.id))
            .join(Dataset, Dataset.id == Sample.dataset_id)
            .filter(Dataset.is_deleted.is_(False), Sample.status != "deleted")
            .group_by(Sample.modality)
            .all()
        )
        return {modality: count for modality, count in rows}

    def dataset_sample_count(self, session, dataset_id: int) -> int:
        return (
            session.query(func.count(Sample.id))
            .filter(Sample.dataset_id == dataset_id, Sample.status != "deleted")
            .scalar()
            or 0
        )

    def dataset_total_size(self, session, dataset_id: int) -> int:
        return (
            session.query(func.coalesce(func.sum(Sample.size_bytes), 0))
            .filter(Sample.dataset_id == dataset_id, Sample.status != "deleted")
            .scalar()
            or 0
        )

    def dataset_modality_breakdown(self, session, dataset_id: int) -> dict[str, int]:
        rows = (
            session.query(Sample.modality, func.count(Sample.id))
            .filter(Sample.dataset_id == dataset_id, Sample.status != "deleted")
            .group_by(Sample.modality)
            .all()
        )
        return {modality: count for modality, count in rows}

    def count_active_datasets(self, session) -> int:
        return session.query(func.count(Dataset.id)).filter(Dataset.is_deleted.is_(False)).scalar() or 0

    def count_active_samples(self, session) -> int:
        return (
            session.query(func.count(Sample.id))
            .join(Dataset, Dataset.id == Sample.dataset_id)
            .filter(Dataset.is_deleted.is_(False), Sample.status != "deleted")
            .scalar()
            or 0
        )

    def delete_sample(self, session, sample: Sample) -> None:
        sample.status = "deleted"

    def soft_delete(self, dataset: Dataset) -> None:
        dataset.is_deleted = True
        dataset.status = "deleted"
        dataset.deleted_at = datetime.now(timezone.utc)

    def update_dataset_counts(self, dataset: Dataset, *, total_samples: int, size_bytes: int) -> None:
        dataset.total_samples = total_samples
        dataset.valid_samples = total_samples
        dataset.size_bytes = size_bytes

    def upsert_statistics(self, session, dataset_id: int, *, total_samples: int, size_bytes: int, modality_breakdown: dict[str, int]):
        row = session.query(DatasetStatistics).filter(DatasetStatistics.dataset_id == dataset_id).first()
        if row is None:
            row = DatasetStatistics(dataset_id=dataset_id)
            session.add(row)
        row.total_samples = total_samples
        row.valid_samples = total_samples
        row.size_bytes = size_bytes
        row.modality_breakdown_json = modality_breakdown
        session.flush()
