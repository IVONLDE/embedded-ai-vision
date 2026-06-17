from __future__ import annotations

from pathlib import Path

from .._compat import slots_dataclass
from agl.algorithm_manager import AlgorithmManager


@slots_dataclass(frozen=True)
class AGLAlgorithmSpec:
    key: str
    name: str
    modality: str
    method_name: str
    output_kind: str
    requires_torch: bool = False


_AGL_ALGORITHM_SPECS = [
    AGLAlgorithmSpec("agl.image.geometric", "AGL Geometric Transformation", "image", "apply_geometric_transformation", "file"),
    AGLAlgorithmSpec("agl.image.style_transfer", "AGL Style Transfer", "image", "apply_style_transfer", "file"),
    AGLAlgorithmSpec("agl.image.color_space", "AGL Color Space Transformation", "image", "apply_color_space_transformation", "file"),
    AGLAlgorithmSpec("agl.image.clarity", "AGL Clarity Transformation", "image", "apply_clarity_transformation", "file"),
    AGLAlgorithmSpec("agl.image.occlusion", "AGL Occlusion Transformation", "image", "apply_occlusion_transformation", "file"),
    AGLAlgorithmSpec("agl.image.environment", "AGL Environment Simulation", "image", "apply_environment_simulation", "file"),
    AGLAlgorithmSpec("agl.image.deformation", "AGL Deformation Distortion", "image", "apply_deformation_distortion", "file"),
    AGLAlgorithmSpec("agl.image.imaging", "AGL Imaging Simulation", "image", "apply_imaging_simulation", "file"),
    AGLAlgorithmSpec("agl.image.channel_processing", "AGL Channel Processing", "image", "apply_channel_processing", "file"),
    AGLAlgorithmSpec("agl.audio.tempo_pitch", "AGL Tempo Pitch Transformation", "audio", "apply_tempo_pitch_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.energy", "AGL Energy Amplitude Transformation", "audio", "apply_energy_amplitude_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.time_series", "AGL Time Series Structure Transformation", "audio", "apply_time_series_structure_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.channel_configuration", "AGL Channel Configuration Transformation", "audio", "apply_channel_configuration_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.specaugment", "AGL SpecAugment Transformation", "audio", "apply_specaugment_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.filter_processing", "AGL Filter Processing Transformation", "audio", "apply_filter_processing_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.environment_noise", "AGL Environment Noise Injection", "audio", "apply_environment_noise_injection_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.spatial_acoustics", "AGL Spatial Acoustics Transformation", "audio", "apply_spatial_acoustics_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.quality_distortion", "AGL Quality Distortion Transformation", "audio", "apply_quality_distortion_transformation", "file"),
    AGLAlgorithmSpec("agl.audio.composite", "AGL Composite Audio Augmentation", "audio", "apply_composite_audio_augmentation", "file"),
    AGLAlgorithmSpec("agl.text.vocabulary_phrase", "AGL Vocabulary Phrase Substitution", "text", "apply_vocabulary_phrase_substitution", "file"),
    AGLAlgorithmSpec("agl.text.structure_noise", "AGL Structure Noise Perturbation", "text", "apply_structure_noise_perturbation", "file"),
    AGLAlgorithmSpec("agl.text.context_embedding", "AGL Context and Embedding Transformation", "text", "apply_context_and_embedding_transformation", "file"),
    AGLAlgorithmSpec("agl.text.style_controlled", "AGL Style Controlled Generation", "text", "apply_style_controlled_generation", "file"),
    AGLAlgorithmSpec("agl.text.reordering", "AGL Sentence or Paragraph Reordering", "text", "apply_sentence_or_paragraph_reordering", "file"),
    AGLAlgorithmSpec("agl.image.gan", "AGL GAN Generation", "image", "generate_with_gan", "file", requires_torch=True),
    AGLAlgorithmSpec("agl.image.diffusion", "AGL Diffusion Generation", "image", "generate_with_diffusion", "file", requires_torch=True),
    AGLAlgorithmSpec("agl.image.transformer", "AGL Transformer Generation", "image", "generate_with_transformer", "file"),
]

_AGL_ALGORITHM_SPEC_BY_KEY = {item.key: item for item in _AGL_ALGORITHM_SPECS}


def list_agl_algorithm_specs() -> list[AGLAlgorithmSpec]:
    return list(_AGL_ALGORITHM_SPECS)


def get_agl_algorithm_spec(key: str) -> AGLAlgorithmSpec:
    try:
        return _AGL_ALGORITHM_SPEC_BY_KEY[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported AGL algorithm key: {key}") from exc


def run_agl_algorithm(*, algorithm_key: str, sample_path: str, parameters: dict, output_dir: str, index: int) -> str | None:
    manager = AlgorithmManager()
    spec = get_agl_algorithm_spec(algorithm_key)
    if spec.requires_torch and not manager._torch_available():
        return None

    method = getattr(manager, spec.method_name, None)
    if method is None:
        raise ValueError(f"AGL method not found for key {algorithm_key}: {spec.method_name}")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    return method(sample_path, parameters or {}, output_dir, index)
