"""Backend extension catalog for demo algorithms and scenario hooks.

The entries here are intentionally lightweight. They document stable keys,
parameter shapes, and extension points so real algorithms can be wired in
later without changing the task orchestration API.
"""

from typing import Any, Dict, List, Optional


def get_cleaning_algorithms(modality: Optional[str] = None) -> List[Dict[str, Any]]:
    items = [
        {
            "key": "image_blur_detection_demo",
            "name": "Image blur detection demo",
            "modality": "image",
            "implemented": True,
            "extension_point": "core.data_cleaning.multi_modal_processor.MultiModalProcessor._detect_image_issues",
            "example": {
                "parameters": {"detect_blur": True, "detect_contrast": True},
                "output": {"suggestion": "deblur", "confidence": 0.85},
            },
        },
        {
            "key": "image_deduplicate_demo",
            "name": "Image aHash deduplicate demo",
            "modality": "image",
            "implemented": True,
            "extension_point": "core.data_cleaning.data_cleaner.DataCleaner._detect_image_duplicates",
            "example": {
                "parameters": {"deduplicate": True, "deduplicate_params": {"hamming_threshold": 0}},
                "output": {"suggestion": "duplicate", "confidence": 1.0},
            },
        },
        {
            "key": "tabular_missing_value_demo",
            "name": "Tabular missing value demo",
            "modality": "tabular",
            "implemented": True,
            "extension_point": "core.data_cleaning.multi_modal_processor.MultiModalProcessor._detect_tabular_issues",
            "example": {
                "parameters": {"detect_missing": True, "handle_missing": True, "fill_value": 0},
                "output": {"suggestion": "handle_missing_values", "confidence": 0.2},
            },
        },
    ]
    return _filter_by_modality(items, modality)


def get_generation_algorithms(modality: Optional[str] = None) -> List[Dict[str, Any]]:
    items = [
        {
            "key": "image_geometric_transform_demo",
            "name": "Image geometric transform demo",
            "modality": "image",
            "implemented": True,
            "aliases": [
                "geometric",
                "geometric_transform",
                "\u57fa\u7840\u51e0\u4f55\u53d8\u6362",
            ],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.apply_geometric_transformation",
            "example": {
                "parameters": {"rotation_degrees": 15, "scale": 1.0, "flip_horizontal": False},
                "output": "enhanced/geometric_0.jpg",
            },
        },
        {
            "key": "image_style_transfer_demo",
            "name": "Image style transfer demo",
            "modality": "image",
            "implemented": True,
            "aliases": ["style", "style_transfer", "\u98ce\u683c\u8fc1\u79fb\u751f\u6210"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.apply_style_transfer",
            "example": {
                "parameters": {"style_strength": 0.7},
                "output": "enhanced/style_0.jpg",
            },
        },
        {
            "key": "audio_noise_demo",
            "name": "Audio noise injection demo",
            "modality": "audio",
            "implemented": True,
            "aliases": ["noise", "add_noise", "\u73af\u5883\u566a\u58f0\u53e0\u52a0"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.add_noise",
            "example": {
                "parameters": {"noise_type": "white", "noise_level": 0.05},
                "output": "enhanced/noisy_0.wav",
            },
        },
        {
            "key": "audio_spectrum_reconstruction_demo",
            "name": "Audio spectrum reconstruction demo",
            "modality": "audio",
            "implemented": True,
            "aliases": ["spectrum", "reconstruct_spectrum", "\u7279\u5f81\u9891\u8c31\u91cd\u6784"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.reconstruct_spectrum",
            "example": {
                "parameters": {"frequency_range": [0, 4000]},
                "output": "enhanced/spectrum_0.wav",
            },
        },
        {
            "key": "text_synonym_replacement_demo",
            "name": "Text synonym replacement demo",
            "modality": "text",
            "implemented": True,
            "aliases": ["synonym", "replace_synonyms", "\u540c\u4e49\u8bcd\u8bed\u4e49\u66ff\u6362"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.replace_synonyms",
            "example": {
                "parameters": {"replace_ratio": 0.3},
                "output": "enhanced/synonyms_0.txt",
            },
        },
        {
            "key": "text_reverse_demo",
            "name": "Text reverse demo",
            "modality": "text",
            "implemented": True,
            "aliases": ["back_translate", "backtranslate", "\u56de\u8bd1\u589e\u5f3a\u903b\u8f91"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.back_translate",
            "example": {
                "parameters": {"target_language": "demo"},
                "output": "enhanced/backtranslate_0.txt",
            },
        },
        {
            "key": "image_gan_demo",
            "name": "Image GAN demo placeholder",
            "modality": "image",
            "implemented": True,
            "aliases": ["gan", "WGAN-GP"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.generate_with_gan",
            "example": {
                "parameters": {"model": "placeholder"},
                "output": "enhanced/gan_0.jpg",
            },
        },
        {
            "key": "image_diffusion_demo",
            "name": "Image diffusion demo placeholder",
            "modality": "image",
            "implemented": True,
            "aliases": ["diffusion", "Diffusion"],
            "extension_point": "core.sample_generation.algorithm_manager.AlgorithmManager.generate_with_diffusion",
            "example": {
                "parameters": {"steps": 50},
                "output": "enhanced/diffusion_0.jpg",
            },
        },
    ]
    return _filter_by_modality(items, modality)


def get_application_scenarios(modality: Optional[str] = None) -> List[Dict[str, Any]]:
    items = [
        {
            "key": "marine_target_detection_demo",
            "name": "Marine target detection demo",
            "modality": "image",
            "model_examples": ["YOLOv8s-Marine", "Faster-RCNN-Base"],
            "extension_point": "core.model_evaluation.ModelEvaluator.start_task",
            "example": {
                "baseline_dataset_id": 1,
                "enhanced_dataset_id": 2,
                "metrics": ["mAP@.5", "Recall", "Precision", "F1-Score"],
            },
        },
        {
            "key": "audio_event_detection_demo",
            "name": "Audio event detection demo",
            "modality": "audio",
            "model_examples": ["Wav2Vec2-Base", "Whisper-Small"],
            "extension_point": "core.simulation_evaluation.ModelEvaluator.process_evaluation_task",
            "example": {
                "baseline_dataset_id": 1,
                "enhanced_dataset_id": 2,
                "metrics": ["accuracy", "recall", "precision", "f1_score"],
            },
        },
        {
            "key": "text_classification_demo",
            "name": "Text classification demo",
            "modality": "text",
            "model_examples": ["BERT-Base", "RoBERTa-Base"],
            "extension_point": "core.simulation_evaluation.ModelEvaluator.process_evaluation_task",
            "example": {
                "baseline_dataset_id": 1,
                "enhanced_dataset_id": 2,
                "metrics": ["accuracy", "recall", "precision", "f1_score"],
            },
        },
    ]
    return _filter_by_modality(items, modality)


def _filter_by_modality(items: List[Dict[str, Any]], modality: Optional[str]) -> List[Dict[str, Any]]:
    if not modality:
        return items
    return [item for item in items if item.get("modality") == modality]
