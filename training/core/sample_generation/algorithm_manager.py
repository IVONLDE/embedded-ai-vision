import os
import re
from typing import Any, Dict, Optional

from ..backend_catalog import get_generation_algorithms


class AlgorithmManager:
    """Demo enhancement algorithms with stable extension points."""

    def get_algorithms(self, modality: Optional[str] = None):
        return get_generation_algorithms(modality)

    def apply_geometric_transformation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import cv2

            img = cv2.imread(image_path)
            if img is None:
                return None

            angle = parameters.get("rotation_degrees", parameters.get("angle", 45))
            scale = parameters.get("scale", 1.0)
            flip_horizontal = parameters.get("flip_horizontal", False)
            flip_vertical = parameters.get("flip_vertical", False)

            height, width = img.shape[:2]
            center = (width // 2, height // 2)
            matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(img, matrix, (width, height))
            img = cv2.resize(img, None, fx=scale, fy=scale)

            if flip_horizontal:
                img = cv2.flip(img, 1)
            if flip_vertical:
                img = cv2.flip(img, 0)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"geometric_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception:
            return None

    def apply_style_transfer(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import cv2

            img = cv2.imread(image_path)
            if img is None:
                return None

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 100, 200)
            edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
            strength = parameters.get("style_strength", parameters.get("strength", 0.7))
            img = cv2.addWeighted(img, 1 - strength, edges, strength, 0)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"style_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception:
            return None

    def add_noise(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import librosa
            import numpy as np
            import soundfile as sf

            y, sr = librosa.load(audio_path)
            noise_type = parameters.get("noise_type", "white")
            noise_level = parameters.get("noise_level", 0.1)

            noise = np.random.randn(len(y))
            if noise_type == "pink":
                noise = np.cumsum(noise) / np.sqrt(np.arange(1, len(y) + 1))

            noise = noise / max(np.max(np.abs(noise)), 1e-12) * noise_level
            y_noisy = y + noise

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"noisy_{index}.wav")
            sf.write(output_path, y_noisy, sr)
            return output_path
        except Exception:
            return None

    def reconstruct_spectrum(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import librosa
            import soundfile as sf

            y, sr = librosa.load(audio_path)
            spectrum = librosa.stft(y)
            min_freq, max_freq = parameters.get("frequency_range", [0, 4000])
            freq_bins = librosa.fft_frequencies(sr=sr)
            mask = (freq_bins >= min_freq) & (freq_bins <= max_freq)
            filtered = spectrum * mask[:, None]
            reconstructed = librosa.istft(filtered)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"spectrum_{index}.wav")
            sf.write(output_path, reconstructed, sr)
            return output_path
        except Exception:
            return None

    def replace_synonyms(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import numpy as np

            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            synonyms = {
                "fast": ["quick", "rapid"],
                "small": ["compact", "tiny"],
                "large": ["big", "huge"],
                "sample": ["example", "instance"],
            }
            replace_ratio = parameters.get("replace_ratio", 0.3)
            words = re.findall(r"\b\w+\b", text)
            new_words = []
            for word in words:
                lower = word.lower()
                if lower in synonyms and np.random.random() < replace_ratio:
                    new_words.append(str(np.random.choice(synonyms[lower])))
                else:
                    new_words.append(word)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"synonyms_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(" ".join(new_words))
            return output_path
        except Exception:
            return None

    def back_translate(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            transformed_text = text[::-1]
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"backtranslate_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(transformed_text)
            return output_path
        except Exception:
            return None

    def generate_with_gan(
        self,
        sample_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import cv2

            img = cv2.imread(sample_path)
            if img is None:
                return None
            img = cv2.flip(img, 1)
            img = cv2.GaussianBlur(img, (5, 5), 0)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"gan_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception:
            return None

    def generate_with_diffusion(
        self,
        sample_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        try:
            import cv2
            import numpy as np

            img = cv2.imread(sample_path)
            if img is None:
                return None
            steps = int(parameters.get("steps", 50))
            for _ in range(max(1, steps // 10)):
                noise = np.random.normal(0, 0.1, img.shape)
                img = np.clip(img + noise, 0, 255).astype(np.uint8)

            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, f"diffusion_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception:
            return None
