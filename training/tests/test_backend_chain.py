import importlib.util
import os
import shutil
import tempfile
import time
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from core.models.dataset import Dataset
from core.models.sample import Sample
from core.data_cleaning.data_cleaner import DataCleaner
from core.sample_generation.sample_generator import SampleGenerator
from core.simulation_evaluation.model_evaluator import ModelEvaluator


class BackendChainTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = create_engine(
            f"sqlite:///{os.path.join(self.tmpdir, 'test.db')}",
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _dataset_with_text_sample(self):
        dataset_path = os.path.join(self.tmpdir, "dataset")
        os.makedirs(dataset_path, exist_ok=True)
        sample_path = os.path.join(dataset_path, "sample.txt")
        with open(sample_path, "w", encoding="utf-8") as f:
            f.write("hello sample")

        dataset = Dataset(
            name="demo",
            type="text",
            storage_path=dataset_path,
            status="processed",
            total_samples=1,
            size=os.path.getsize(sample_path),
        )
        self.db.add(dataset)
        self.db.commit()
        self.db.refresh(dataset)

        sample = Sample(
            dataset_id=dataset.id,
            name="sample.txt",
            path=sample_path,
            size=os.path.getsize(sample_path),
            type="text",
            status="raw",
            sample_metadata={},
        )
        self.db.add(sample)
        self.db.commit()
        return dataset

    def test_fastapi_package_is_not_desktop_main_path(self):
        self.assertIsNone(importlib.util.find_spec("api"))

    def test_sample_generator_start_and_stop_wrappers_match_backend_service_calls(self):
        dataset = self._dataset_with_text_sample()
        generator = SampleGenerator(self.db, session_factory=self.SessionLocal)

        task = generator.create_enhancement_task(
            dataset.id,
            "text_reverse_demo",
            {},
            1,
        )
        start_result = generator.start_task(task.id, background=False)

        self.assertEqual(start_result["status"], "success")
        refreshed = generator.get_enhancement_task(task.id)
        self.assertEqual(refreshed.status, "completed")
        self.assertEqual(refreshed.progress, 100)

        task2 = generator.create_enhancement_task(
            dataset.id,
            "text_reverse_demo",
            {},
            1,
        )
        stop_result = generator.stop_task(task2.id)
        self.assertEqual(stop_result["status"], "success")
        self.assertEqual(generator.get_enhancement_task(task2.id).status, "stopped")

    def test_sample_generator_sync_start_returns_processing_failure(self):
        dataset = self._dataset_with_text_sample()
        generator = SampleGenerator(self.db, session_factory=self.SessionLocal)
        task = generator.create_enhancement_task(dataset.id, "missing_algorithm", {}, 1)

        result = generator.start_task(task.id, background=False)

        self.assertEqual(result["status"], "error")
        self.assertIn("generated 0/1", result["message"])
        self.assertEqual(generator.get_enhancement_task(task.id).status, "failed")

    def test_data_cleaner_sync_start_returns_processing_failure(self):
        dataset = self._dataset_with_text_sample()
        cleaner = DataCleaner(self.db, session_factory=self.SessionLocal)
        task = cleaner.create_cleaning_task(dataset.id, "text", {})

        def fail_quality_check(*args, **kwargs):
            raise RuntimeError("quality engine unavailable")

        cleaner.multi_modal_processor.detect_quality_issues = fail_quality_check
        result = cleaner.start_task(task.id, background=False)

        self.assertEqual(result["status"], "error")
        self.assertIn("quality engine unavailable", result["message"])
        self.assertEqual(cleaner.get_cleaning_task(task.id).status, "failed")

    def test_model_evaluator_sync_start_returns_processing_failure(self):
        baseline = self._dataset_with_text_sample()
        enhanced = Dataset(
            name="enhanced",
            type="text",
            storage_path=os.path.join(self.tmpdir, "enhanced"),
            status="processed",
            total_samples=0,
            size=0,
        )
        self.db.add(enhanced)
        self.db.commit()
        self.db.refresh(enhanced)

        evaluator = ModelEvaluator(self.db, session_factory=self.SessionLocal)
        task = evaluator.create_evaluation_task("demo", baseline.id, enhanced.id, "demo-model")

        def fail_training(*args, **kwargs):
            raise RuntimeError("trainer unavailable")

        evaluator.performance_analyzer.train_model = fail_training
        result = evaluator.start_task(task.id, background=False)

        self.assertEqual(result["status"], "error")
        self.assertIn("trainer unavailable", result["message"])
        self.assertEqual(evaluator.get_evaluation_task(task.id).status, "failed")

    def test_sample_generator_background_start_uses_fresh_session(self):
        dataset = self._dataset_with_text_sample()
        generator = SampleGenerator(self.db, session_factory=self.SessionLocal)
        task = generator.create_enhancement_task(dataset.id, "text_reverse_demo", {}, 1)

        result = generator.start_task(task.id, background=True)

        self.assertEqual(result["status"], "success")
        deadline = time.time() + 5
        status = None
        while time.time() < deadline:
            with self.SessionLocal() as check_db:
                status = check_db.query(type(task)).filter(type(task).id == task.id).first().status
            if status == "completed":
                break
            time.sleep(0.05)
        self.assertEqual(status, "completed")

    def test_deblur_image_lazy_import_order(self):
        try:
            import numpy as np
        except Exception as exc:
            self.skipTest(f"numpy unavailable: {exc}")

        from core.data_cleaning.multi_modal_processor import MultiModalProcessor

        img = np.zeros((3, 3, 3), dtype=np.uint8)
        result = MultiModalProcessor()._deblur_image(img)
        self.assertEqual(result.shape, img.shape)

    def test_backend_catalog_exposes_sample_cleaning_generation_and_scenario_interfaces(self):
        from core.backend_catalog import (
            get_application_scenarios,
            get_cleaning_algorithms,
            get_generation_algorithms,
        )

        cleaning = get_cleaning_algorithms()
        generation = get_generation_algorithms()
        scenarios = get_application_scenarios()

        self.assertTrue(any(item["key"] == "image_blur_detection_demo" for item in cleaning))
        self.assertTrue(any(item["key"] == "text_reverse_demo" for item in generation))
        self.assertTrue(any(item["key"] == "marine_target_detection_demo" for item in scenarios))

        for item in cleaning + generation + scenarios:
            self.assertIn("key", item)
            self.assertIn("extension_point", item)
            self.assertIn("example", item)

    def test_generation_catalog_matches_supported_generator_keys_and_legacy_aliases(self):
        from core.backend_catalog import get_generation_algorithms

        catalog_keys = {item["key"] for item in get_generation_algorithms()}
        expected_keys = {
            "image_geometric_transform_demo",
            "image_style_transfer_demo",
            "audio_noise_demo",
            "audio_spectrum_reconstruction_demo",
            "text_synonym_replacement_demo",
            "text_reverse_demo",
            "image_gan_demo",
            "image_diffusion_demo",
        }

        self.assertEqual(expected_keys, catalog_keys)

        dataset = self._dataset_with_text_sample()
        generator = SampleGenerator(self.db, session_factory=self.SessionLocal)
        task = generator.create_enhancement_task(
            dataset.id,
            "\u56de\u8bd1\u589e\u5f3a\u903b\u8f91",
            {},
            1,
        )

        result = generator.start_task(task.id, background=False)

        self.assertEqual(result["status"], "success")
        self.assertEqual(generator.get_enhancement_task(task.id).status, "completed")

    def test_algorithm_manager_keeps_gui_algorithm_list_contract(self):
        from core.sample_generation.algorithm_manager import AlgorithmManager

        algorithms = AlgorithmManager().get_algorithms("text")

        self.assertTrue(any(item["key"] == "text_reverse_demo" for item in algorithms))
        self.assertTrue(all(item["modality"] == "text" for item in algorithms))


if __name__ == "__main__":
    unittest.main()
