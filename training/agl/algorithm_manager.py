from __future__ import annotations

import os
import cv2
import numpy as np
import re
from typing import Dict, Any, Optional, List, Tuple

# 注意：本项目的“清洗/增强”同时覆盖图像/音频/文本。
# 但当前运行环境不一定同时安装了所有音频依赖（例如 librosa/soundfile）。
# 为了保证“只做图像增强”也能正常工作，这里把音频依赖做成可选导入。
try:
    import librosa  # type: ignore
except Exception:
    librosa = None

try:
    import soundfile as sf  # type: ignore
except Exception:
    sf = None

# 深度学习生成（WGAN-GP / Diffusion）
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
except Exception:
    torch = None
    nn = None
    optim = None

class AlgorithmManager:
    def _torch_available(self) -> bool:
        return torch is not None and nn is not None and optim is not None

    def apply_geometric_transformation(self, image_path: str, parameters: Dict[str, Any], 
                                    output_dir: str, index: int) -> Optional[str]:
        """应用几何变换"""
        try:
            # 读取图像
            img = cv2.imread(image_path)
            if img is None:
                return None
            
            # 旋转
            angle = parameters.get('旋转角度', 45)
            height, width = img.shape[:2]
            center = (width // 2, height // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            img = cv2.warpAffine(img, M, (width, height))
            
            # 缩放
            scale = parameters.get('缩放比例', 1.0)
            img = cv2.resize(img, None, fx=scale, fy=scale)
            
            # 水平翻转
            if parameters.get('水平翻转', False):
                img = cv2.flip(img, 1)
            
            # 垂直翻转
            if parameters.get('垂直翻转', False):
                img = cv2.flip(img, 0)
            
            # 保存结果
            output_path = os.path.join(output_dir, f"geometric_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception:
            return None

    def apply_style_transfer(self, image_path: str, parameters: Dict[str, Any], 
                          output_dir: str, index: int) -> Optional[str]:
        """应用风格迁移"""
        try:
            # 读取图像
            img = cv2.imread(image_path)
            if img is None:
                return None
            
            # 使用OpenCV的风格迁移（简化版）
            # 实际应用中可能需要使用更复杂的模型
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 100, 200)
            edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
            
            # 风格强度
            strength = parameters.get('风格强度', 0.7)
            img = cv2.addWeighted(img, 1 - strength, edges, strength, 0)
            
            # 保存结果
            output_path = os.path.join(output_dir, f"style_{index}.jpg")
            cv2.imwrite(output_path, img)
            return output_path
        except Exception as e:
            print(f"Error detail: {e}") # 打印出具体的报错信息
            return None

    # =========================
    # 2. 色域变换（亮度/颜色抖动/PCA）
    # =========================
    def apply_color_space_transformation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """对图像做亮度/饱和度/对比度抖动，并可选做 PCA Lighting。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            # BGR -> 处理用 float
            img_f = img.astype(np.float32)

            # 1) 亮度/对比度调整
            # brightness_delta: [-255,255] 之间的偏移量；contrast_alpha: 对比度缩放
            brightness_delta = float(parameters.get("亮度调整值", 0.0))
            contrast_alpha = float(parameters.get("对比度缩放", 1.0))
            img_f = img_f * contrast_alpha + brightness_delta

            # 2) 颜色抖动（在 HSV 上调饱和度 / 可选色相）
            sat_scale = float(parameters.get("饱和度缩放", 1.0))
            hue_delta = float(parameters.get("色相偏移", 0.0))  # OpenCV hue: [0,179]
            hsv = cv2.cvtColor(np.clip(img_f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[..., 1] = np.clip(hsv[..., 1] * sat_scale, 0, 255)
            hsv[..., 0] = (hsv[..., 0] + hue_delta) % 180
            img_f = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

            # 3) PCA Lighting（AlexNet 风格）
            pca_strength = float(parameters.get("PCA抖动强度", 0.0))
            if pca_strength != 0.0:
                # 取像素作为样本计算 3x3 协方差
                pixels = img_f.reshape(-1, 3)
                mean = np.mean(pixels, axis=0, keepdims=True)
                centered = pixels - mean
                cov = np.cov(centered, rowvar=False)
                eigvals, eigvecs = np.linalg.eigh(cov)  # ascending
                # 取最大的特征方向
                order = np.argsort(eigvals)[::-1]
                eigvals = eigvals[order]
                eigvecs = eigvecs[:, order]
                # alpha 服从 N(0,1)
                alpha = np.random.normal(0, 1, size=(3,)).astype(np.float32)
                # lighting = eigvecs * (eigvals^0.5 * alpha) * strength
                lighting = eigvecs @ (np.sqrt(np.maximum(eigvals, 0)) * alpha)
                img_f = img_f + lighting.astype(np.float32) * pca_strength

            img_out = np.clip(img_f, 0, 255).astype(np.uint8)
            output_path = os.path.join(output_dir, f"color_{index}.jpg")
            cv2.imwrite(output_path, img_out)
            return output_path
        except Exception:
            return None

    # =========================
    # 3. 清晰度变换（模糊 / 锐化）
    # =========================
    def apply_clarity_transformation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """模拟不同清晰度：可选 Gaussian 模糊与 Unsharp Mask 锐化。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            blur_strength = float(parameters.get("模糊强度", 0.0))  # 0~1
            sharp_strength = float(parameters.get("锐化强度", 0.0))  # 0~1

            out = img
            if blur_strength > 0:
                # 根据强度选择 kernel：必须是奇数
                k = int(parameters.get("模糊核大小", 5))
                k = max(3, k)
                if k % 2 == 0:
                    k += 1
                k = int(min(k + int(blur_strength * 10), 31))
                out = cv2.GaussianBlur(out, (k, k), 0)

            if sharp_strength > 0:
                amount = float(parameters.get("锐化量", sharp_strength))  # unsharp amount
                amount = max(0.0, amount)
                blurred = cv2.GaussianBlur(out, (0 if False else 3, 3), 1.0)
                # unsharp: out + amount*(out-blurred)
                out = cv2.addWeighted(out, 1.0 + amount, blurred, -amount, 0)

            output_path = os.path.join(output_dir, f"clarity_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None

    # =========================
    # 5. 擦除/遮挡（Random Erasing / Cutout / GridMask）
    # =========================
    def apply_occlusion_transformation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """对图像做遮挡增强：random erasing / cutout / gridmask。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            h, w = img.shape[:2]
            mode = str(parameters.get("遮挡类型", "random_erasing"))
            out = img.copy()

            fill_mode = str(parameters.get("填充值模式", "mean"))  # mean/random/zero
            fill_color = None
            if fill_mode == "mean":
                fill_color = tuple(int(x) for x in np.mean(out.reshape(-1, 3), axis=0))
            elif fill_mode == "zero":
                fill_color = (0, 0, 0)

            def _fill_rect(x, y, ww, hh):
                nonlocal fill_color
                if fill_color is None and fill_mode == "random":
                    fill_color = tuple(int(x) for x in np.random.randint(0, 256, size=(3,)))
                cv2.rectangle(out, (x, y), (x + ww, y + hh), fill_color, thickness=-1)

            if mode == "random_erasing":
                count = int(parameters.get("擦除次数", 1))
                area_ratio = float(parameters.get("擦除面积比例", 0.2))
                min_aspect = float(parameters.get("最小宽高比", 0.3))
                max_aspect = float(parameters.get("最大宽高比", 3.0))
                for _ in range(max(1, count)):
                    target_area = h * w * area_ratio
                    aspect = np.random.uniform(min_aspect, max_aspect)
                    hh = int(round(np.sqrt(target_area / aspect)))
                    ww = int(round(aspect * hh))
                    if hh <= 0 or ww <= 0:
                        continue
                    hh = min(hh, h // 2)
                    ww = min(ww, w // 2)
                    x = int(np.random.randint(0, max(1, w - ww)))
                    y = int(np.random.randint(0, max(1, h - hh)))
                    _fill_rect(x, y, ww, hh)

            elif mode == "cutout":
                count = int(parameters.get("切块数量", 1))
                cut_ratio = float(parameters.get("切块面积比例", 0.25))
                for _ in range(max(1, count)):
                    ww = int(np.sqrt(w * h * cut_ratio))
                    hh = ww
                    ww = min(ww, w // 2)
                    hh = min(hh, h // 2)
                    x = int(np.random.randint(0, max(1, w - ww)))
                    y = int(np.random.randint(0, max(1, h - hh)))
                    _fill_rect(x, y, ww, hh)

            elif mode == "gridmask":
                grid_size = int(parameters.get("栅格大小", 32))
                ratio = float(parameters.get("遮罩比例", 0.4))  # 每个栅格遮掉多少宽度
                ratio = max(0.0, min(ratio, 1.0))
                # 用格子生成“条带遮罩”
                mask = np.ones((h, w), dtype=np.uint8)
                if grid_size <= 0:
                    grid_size = 16
                stripe = int(grid_size * ratio)
                stripe = max(1, stripe)
                for yy in range(0, h, grid_size):
                    for xx in range(0, w, grid_size):
                        # 随机决定遮上半部分还是下半部分
                        if np.random.rand() < 0.5:
                            mask[yy : min(h, yy + stripe), xx : min(w, xx + grid_size)] = 0
                        else:
                            mask[yy : min(h, yy + grid_size), xx : min(w, xx + stripe)] = 0
                mask_3 = np.repeat(mask[:, :, None], 3, axis=2)
                if fill_color is None:
                    fill_color = (0, 0, 0)
                out = out * mask_3 + (1 - mask_3) * np.array(fill_color, dtype=np.uint8)

            else:
                # 未知模式：退化为 random_erasing
                return self.apply_occlusion_transformation(
                    image_path,
                    {**parameters, "遮挡类型": "random_erasing"},
                    output_dir,
                    index,
                )

            output_path = os.path.join(output_dir, f"occlusion_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None

    # =========================
    # 6. 环境模拟（雾/雪/阴影）
    # =========================
    def apply_environment_simulation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """模拟雾、雪与阴影：通过混合/叠加方式生成真实感退化。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            h, w = img.shape[:2]
            out = img.astype(np.float32)

            # 雾
            fog_strength = float(parameters.get("雾气浓度", 0.0))  # 0~1
            if fog_strength > 0:
                # 深度图用随机噪声模糊近似
                depth = np.random.rand(h, w).astype(np.float32)
                depth = cv2.GaussianBlur(depth, (0 if False else 51, 51), 0)
                depth = depth - depth.min()
                depth = depth / (depth.max() + 1e-6)
                trans = np.exp(-fog_strength * 2.0 * depth)  # 越远越浑浊
                trans = trans[..., None]
                airlight = np.array([200, 200, 200], dtype=np.float32)
                out = out * trans + airlight * (1.0 - trans)

            # 雪
            snow_strength = float(parameters.get("雪强度", 0.0))  # 0~1
            if snow_strength > 0:
                snow = np.zeros((h, w), dtype=np.uint8)
                # 雪点数量与强度相关
                n_snow = int((h * w) * 0.00005 * snow_strength + 30 * snow_strength)
                n_snow = max(10, n_snow)
                for _ in range(n_snow):
                    x = int(np.random.randint(0, w))
                    y = int(np.random.randint(0, h))
                    r = int(np.random.randint(1, 3 + int(3 * snow_strength)))
                    cv2.circle(snow, (x, y), r, 255, -1)
                snow = cv2.GaussianBlur(snow, (0 if False else 9, 9), 0).astype(np.float32) / 255.0
                # 把雪点叠加为白色偏移
                out = out * (1.0 - 0.5 * snow_strength) + 255.0 * snow[..., None] * (0.5 * snow_strength)

            # 阴影（椭圆暗化 + 模糊）
            shadow_strength = float(parameters.get("阴影强度", 0.0))  # 0~1
            if shadow_strength > 0:
                mask = np.ones((h, w), dtype=np.float32)
                # 随机生成 1~2 个椭圆遮罩
                n_ell = 1 + int(shadow_strength > 0.2)
                for _ in range(n_ell):
                    cx = int(np.random.randint(0, w))
                    cy = int(np.random.randint(0, h))
                    ax = int(w * np.random.uniform(0.3, 0.8))
                    ay = int(h * np.random.uniform(0.3, 0.8))
                    angle = float(np.random.uniform(0, 180))
                    ellipse = np.zeros((h, w), dtype=np.uint8)
                    cv2.ellipse(ellipse, (cx, cy), (ax, ay), angle, 0, 360, 255, -1)
                    ellipse = cv2.GaussianBlur(ellipse.astype(np.float32), (0 if False else 31, 31), 0)
                    ellipse = ellipse / 255.0
                    # 阴影：乘以一个 <1 的因子
                    mask = mask * (1.0 - ellipse * 0.6 * shadow_strength)
                out = out * mask[..., None]

            out = np.clip(out, 0, 255).astype(np.uint8)
            output_path = os.path.join(output_dir, f"env_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None

    # =========================
    # 7. 形变/畸变（弹性变形 / 光学畸变）
    # =========================
    def apply_deformation_distortion(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """弹性形变与径向畸变（镜头缺陷）增强。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            out = img
            h, w = img.shape[:2]

            # 弹性形变
            elastic_strength = float(parameters.get("弹性强度", 0.0))  # 0~100 左右
            elastic_sigma = float(parameters.get("弹性高斯核", 10.0))
            if elastic_strength > 0:
                alpha = elastic_strength
                sigma = elastic_sigma
                # 生成位移场并用高斯平滑
                dx = (np.random.rand(h, w).astype(np.float32) * 2 - 1)
                dy = (np.random.rand(h, w).astype(np.float32) * 2 - 1)
                dx = cv2.GaussianBlur(dx, (0 if False else 51, 51), sigma)
                dy = cv2.GaussianBlur(dy, (0 if False else 51, 51), sigma)
                dx = dx * alpha / 100.0
                dy = dy * alpha / 100.0

                x, y = np.meshgrid(np.arange(w), np.arange(h))
                map_x = (x + dx).astype(np.float32)
                map_y = (y + dy).astype(np.float32)
                out = cv2.remap(out, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            # 光学畸变（径向畸变模型）
            k1 = float(parameters.get("畸变系数k1", 0.0))
            k2 = float(parameters.get("畸变系数k2", 0.0))
            if k1 != 0.0 or k2 != 0.0:
                # 归一化坐标到 [-1,1]
                xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)
                ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)
                xv, yv = np.meshgrid(xs, ys)
                r2 = xv * xv + yv * yv
                factor = 1.0 + k1 * r2 + k2 * (r2 ** 2)
                x_dist = xv * factor
                y_dist = yv * factor

                # 映射到像素坐标
                map_x = ((x_dist + 1.0) * 0.5 * (w - 1)).astype(np.float32)
                map_y = ((y_dist + 1.0) * 0.5 * (h - 1)).astype(np.float32)
                out = cv2.remap(out, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

            output_path = os.path.join(output_dir, f"deform_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None

    # =========================
    # 8. 成像模拟（传感器噪声 / 成像链路）
    # =========================
    def apply_imaging_simulation(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """模拟成像链路：可选低通模糊 + 下采样 + 传感器噪声（shot/read）。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            out = img.astype(np.float32) / 255.0
            shot_strength = float(parameters.get("散粒噪声强度", 0.0))
            read_noise_sigma = float(parameters.get("读出噪声sigma", 0.0))

            # 模糊（模拟光学低通/运动）
            blur_kernel = int(parameters.get("成像模糊核大小", 0))
            if blur_kernel and blur_kernel > 1:
                k = blur_kernel
                if k % 2 == 0:
                    k += 1
                out = cv2.GaussianBlur(out, (k, k), 0)

            # 下采样（模拟链路分辨率损失）
            downsample = float(parameters.get("下采样比例", 1.0))
            if downsample < 1.0 and downsample > 0:
                h, w = out.shape[:2]
                nh = max(1, int(h * downsample))
                nw = max(1, int(w * downsample))
                small = cv2.resize(out, (nw, nh), interpolation=cv2.INTER_AREA)
                out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

            # 传感器噪声：用高斯近似（保证稳定、速度快）
            if shot_strength > 0:
                # shot variance 与强度相关：sqrt(intensity) 近似
                shot_std = np.sqrt(np.clip(out, 0, 1)) * shot_strength
                out = out + np.random.normal(0, shot_std, size=out.shape).astype(np.float32)

            if read_noise_sigma > 0:
                out = out + np.random.normal(0, read_noise_sigma, size=out.shape).astype(np.float32)

            out = np.clip(out, 0.0, 1.0)
            out_u8 = (out * 255.0).astype(np.uint8)
            output_path = os.path.join(output_dir, f"imaging_{index}.jpg")
            cv2.imwrite(output_path, out_u8)
            return output_path
        except Exception:
            return None

    # =========================
    # 9. 通道处理（通道混洗）
    # =========================
    def apply_channel_processing(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """通道混洗：随机打乱 BGR 顺序，减少对单通道的过拟合依赖。"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            do_shuffle = bool(parameters.get("是否混洗", True))
            if not do_shuffle:
                return None

            # cv2 读入为 BGR
            perm = np.random.permutation(3)
            out = img[:, :, perm].copy()
            output_path = os.path.join(output_dir, f"channel_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None

    # =========================
    # 14. 跨模态融合（红外+可见光）
    # =========================
    def apply_cross_modal_fusion(
        self,
        image_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """跨模态融合的“可跑降级版”：单张图生成伪红外，再融合到可见光的亮度通道。

        说明：当前增强框架一次只传入一张样本图像（没有 IR/VIS 成对输入），
        因此这里退化为“单张伪融合”，用于补齐功能链路与 UI/参数流程。
        若你后续能提供成对配对规则（或 metadata pair_id），我可以把它升级为真正的 IR+VIS 成对融合。
        """
        try:
            img = cv2.imread(image_path)
            if img is None:
                return None
            if len(img.shape) == 2:
                img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            # 生成伪 IR：灰度 + CLAHE + 归一化
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            clahe_clip = float(parameters.get("CLAHE剪切值", 2.0))
            clahe = cv2.createCLAHE(clipLimit=max(0.1, clahe_clip), tileGridSize=(8, 8))
            ir = clahe.apply(gray).astype(np.float32)
            ir = (ir - ir.min()) / (ir.max() - ir.min() + 1e-6)  # [0,1]

            # 在 HSV 的 V 通道上做融合
            vis_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
            v = vis_hsv[..., 2] / 255.0
            ir_weight = float(parameters.get("融合权重IR", 0.5))  # 0~1
            ir_weight = max(0.0, min(ir_weight, 1.0))
            v_new = (1.0 - ir_weight) * v + ir_weight * ir
            vis_hsv[..., 2] = np.clip(v_new * 255.0, 0, 255)
            out = cv2.cvtColor(vis_hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

            output_path = os.path.join(output_dir, f"fusion_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None
  
    def add_noise(self, audio_path: str, parameters: Dict[str, Any], 
                 output_dir: str, index: int) -> Optional[str]:
        """添加噪声"""
        try:
            if librosa is None or sf is None:
                # 音频增强依赖缺失（例如当前环境未安装 librosa / soundfile）
                return None

            # 读取音频
            y, sr = librosa.load(audio_path)
            
            # 生成噪声
            noise_type = parameters.get('噪声类型', 'white')
            noise_level = parameters.get('噪声强度', 0.1)
            
            if noise_type == 'white':
                noise = np.random.randn(len(y))
            elif noise_type == 'pink':
                # 简化的粉红噪声生成
                noise = np.random.randn(len(y))
                noise = np.cumsum(noise) / np.sqrt(np.arange(1, len(y) + 1))
            else:
                noise = np.random.randn(len(y))
            
            # 归一化噪声
            noise = noise / np.max(np.abs(noise)) * noise_level
            
            # 添加噪声
            y_noisy = y + noise
            
            # 保存结果
            output_path = os.path.join(output_dir, f"noisy_{index}.wav")
            sf.write(output_path, y_noisy, sr)
            return output_path
        except Exception:
            return None

    def reconstruct_spectrum(self, audio_path: str, parameters: Dict[str, Any],
                           output_dir: str, index: int) -> Optional[str]:
        """重构频谱"""
        try:
            if librosa is None or sf is None:
                # 音频增强依赖缺失（例如当前环境未安装 librosa / soundfile）
                return None

            # 读取音频
            y, sr = librosa.load(audio_path)
            
            # 计算频谱
            D = librosa.stft(y)
            
            # 获取频谱范围
            freq_range = parameters.get('频谱范围', [0, 4000])
            min_freq, max_freq = freq_range
            
            # 计算频率 bins
            freq_bins = librosa.fft_frequencies(sr=sr)
            mask = (freq_bins >= min_freq) & (freq_bins <= max_freq)
            
            # 应用掩码
            D_filtered = D * mask[np.newaxis, :]
            
            # 重构信号
            y_reconstructed = librosa.istft(D_filtered)
            
            # 保存结果
            output_path = os.path.join(output_dir, f"spectrum_{index}.wav")
            sf.write(output_path, y_reconstructed, sr)
            return output_path
        except Exception:
            return None

    # =========================
    # 音频增强（时域/频域/环境/复合）
    # =========================
    def _load_audio(self, audio_path: str) -> Optional[Tuple[np.ndarray, int]]:
        """加载音频（尽量保留声道）。

        返回：
        - y: (C, T) 的 numpy 数组；C=声道数
        - sr: 采样率
        """
        try:
            if librosa is None:
                return None
            y, sr = librosa.load(audio_path, sr=None, mono=False)
            if y.ndim == 1:
                y = y[np.newaxis, :]
            return y, sr
        except Exception:
            return None

    def _save_audio(self, y: np.ndarray, sr: int, output_path: str) -> Optional[str]:
        """保存音频到 wav。"""
        try:
            if sf is None:
                return None
            y = np.asarray(y)
            # 允许 y 为 (T,) 或 (C,T)
            if y.ndim == 1:
                y_out = y
            else:
                # soundfile 通常期望 (T, C)
                y_out = y.T

            # 避免过载削波
            peak = float(np.max(np.abs(y_out))) if y_out.size else 0.0
            if peak > 1.0:
                y_out = y_out / (peak + 1e-6) * 0.999

            sf.write(output_path, y_out, sr)
            return output_path
        except Exception:
            return None

    def _match_length(self, y: np.ndarray, target_len: int) -> np.ndarray:
        """把音频拉伸/裁剪/补零到指定长度（y: (C,T)）。"""
        if y.shape[-1] == target_len:
            return y
        if y.shape[-1] > target_len:
            return y[..., :target_len]
        pad = target_len - y.shape[-1]
        return np.pad(y, ((0, 0), (0, pad)), mode="constant")

    def apply_tempo_pitch_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """时域增强 1：语速与音调

        支持：
        - 时间拉伸/压缩（librosa time_stretch，rate）
        - 音高偏移（librosa pitch_shift，半音 n_steps）
        """
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded  # (C,T)
            target_len = y.shape[-1]

            rate = float(parameters.get("时间拉伸速率", 1.0))
            n_steps = float(parameters.get("音高半音偏移", 0.0))

            y_out = y.copy()
            # 1) 速度变化（时间拉伸）
            if rate > 0 and abs(rate - 1.0) > 1e-6:
                stretched = []
                for c in range(y_out.shape[0]):
                    yt = librosa.effects.time_stretch(y_out[c], rate=rate)
                    yt = self._match_length(yt[np.newaxis, :], target_len)[0]
                    stretched.append(yt)
                y_out = np.stack(stretched, axis=0)

            # 2) 音高变化（半音）
            if abs(n_steps) > 1e-6:
                pitched = []
                for c in range(y_out.shape[0]):
                    yp = librosa.effects.pitch_shift(y_out[c], sr=sr, n_steps=n_steps)
                    yp = self._match_length(yp[np.newaxis, :], target_len)[0]
                    pitched.append(yp)
                y_out = np.stack(pitched, axis=0)

            output_path = os.path.join(output_dir, f"tempo_pitch_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_energy_amplitude_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """时域增强 2：能量与幅度（音量调整/静音插入）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            target_len = y.shape[-1]

            gain = float(parameters.get("音量缩放", 1.0))
            gain = max(0.0, gain)
            y_out = y * gain

            # 静音插入
            silence_prob = float(parameters.get("静音概率", 0.5))
            silence_times = int(parameters.get("静音次数", 1))
            silence_min_sec = float(parameters.get("静音最短秒", 0.05))
            silence_max_sec = float(parameters.get("静音最长秒", 0.2))
            silence_times = max(1, silence_times)

            if np.random.rand() < silence_prob:
                for _ in range(silence_times):
                    seg_len = int(np.random.uniform(silence_min_sec, silence_max_sec) * sr)
                    seg_len = max(1, min(seg_len, target_len))
                    start = int(np.random.randint(0, max(1, target_len - seg_len)))
                    y_out[:, start : start + seg_len] = 0.0

            output_path = os.path.join(output_dir, f"energy_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_time_series_structure_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """时域增强 3：时序与结构

        支持：
        - 时间偏移（零填充 shift）
        - 循环旋转（roll）
        - 音频剪裁/拼接（从原音随机分段拼起来，再裁剪到原长）
        - 音频反转（reverse）
        """
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded  # (C,T)
            T = y.shape[-1]

            op = str(parameters.get("时序操作类型", "mix")).lower()
            max_shift_sec = float(parameters.get("最大时间偏移秒", 0.2))
            crop_ratio = float(parameters.get("裁剪比例", 0.9))
            concat_parts = int(parameters.get("拼接段数", 2))
            reverse_prob = float(parameters.get("反转概率", 0.5))

            y_out = y.copy()

            def _shift_zero(x: np.ndarray, shift: int) -> np.ndarray:
                if shift == 0:
                    return x
                out = np.zeros_like(x)
                if shift > 0:
                    out[:, shift:] = x[:, : x.shape[1] - shift]
                else:
                    s = -shift
                    out[:, : x.shape[1] - s] = x[:, s:]
                return out

            def _rotate_roll(x: np.ndarray, shift: int) -> np.ndarray:
                if shift == 0:
                    return x
                return np.roll(x, shift=shift, axis=-1)

            def _crop_pad(x: np.ndarray, ratio: float) -> np.ndarray:
                ratio = max(0.1, min(ratio, 1.0))
                L = int(T * ratio)
                L = max(1, min(L, T))
                start = int(np.random.randint(0, max(1, T - L + 1)))
                seg = x[:, start : start + L]
                return self._match_length(seg, T)

            def _concat(x: np.ndarray, parts: int) -> np.ndarray:
                parts = max(2, parts)
                # 每段长度固定，最后再裁剪到原长
                part_len = max(1, T // parts)
                segs = []
                for _ in range(parts):
                    start = int(np.random.randint(0, max(1, T - part_len + 1)))
                    segs.append(x[:, start : start + part_len])
                cat = np.concatenate(segs, axis=-1)
                return self._match_length(cat, T)

            choices = ["shift", "rotate", "crop", "concat", "reverse"]
            if op == "mix":
                selected = np.random.choice(choices, size=2, replace=False)
            else:
                selected = [op]

            for s in selected:
                if s == "shift":
                    shift = int(np.random.uniform(-max_shift_sec, max_shift_sec) * sr)
                    y_out = _shift_zero(y_out, shift)
                elif s == "rotate":
                    shift = int(np.random.uniform(-max_shift_sec, max_shift_sec) * sr)
                    y_out = _rotate_roll(y_out, shift)
                elif s == "crop":
                    y_out = _crop_pad(y_out, crop_ratio)
                elif s == "concat":
                    y_out = _concat(y_out, concat_parts)
                elif s == "reverse":
                    if np.random.rand() < reverse_prob:
                        y_out = y_out[:, ::-1].copy()

            # 额外反转（mix 时可选强化）
            if op == "mix" and np.random.rand() < reverse_prob:
                y_out = y_out[:, ::-1].copy()

            output_path = os.path.join(output_dir, f"timeseries_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_channel_configuration_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """时域增强 4：声道配置（模拟单/多声道兼容）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded  # (C,T)
            C, T = y.shape

            target_channels = str(parameters.get("目标声道", "auto")).lower()
            # auto：随机选择 mono 或 stereo
            if target_channels == "auto":
                target_channels = "mono" if (np.random.rand() < 0.5) else "stereo"

            y_out = y.copy()
            if target_channels == "mono":
                if C == 1:
                    y_out = y_out[:1]
                else:
                    mix_strategy = str(parameters.get("混合策略", "avg")).lower()
                    if mix_strategy == "random_weight" and C >= 2:
                        w = np.random.rand(C).astype(np.float32)
                        w = w / (w.sum() + 1e-6)
                        y_out = np.sum(y_out * w[:, None], axis=0, keepdims=True)
                    else:
                        y_out = np.mean(y_out, axis=0, keepdims=True)
            elif target_channels == "stereo":
                if C == 1:
                    # mono -> stereo（复制并加入微弱抖动，模拟设备差异）
                    jitter = float(parameters.get("立体声微抖动", 0.002))
                    ch1 = y_out[0]
                    ch2 = y_out[0] * (1.0 + np.random.uniform(-jitter, jitter))
                    y_out = np.stack([ch1, ch2], axis=0)
                else:
                    # stereo 或多声道：至少保证前两个声道
                    if C >= 2:
                        swap_prob = float(parameters.get("左右交换概率", 0.2))
                        left, right = y_out[0], y_out[1]
                        if np.random.rand() < swap_prob:
                            left, right = right, left
                        # 只取两个声道，避免 soundfile 保存更复杂形状
                        y_out = np.stack([left, right], axis=0)
            else:
                # 不识别目标声道，直接返回原始
                y_out = y

            output_path = os.path.join(output_dir, f"channels_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_specaugment_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """频域增强 5：SpecAugment（mel 频谱随机遮挡）。

        实现思路：
        - 计算 mel power spectrogram
        - 随机在频率维与时间维置零若干块
        - 用 librosa 的 mel_to_audio 近似反演回波形
        """
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            n_mels = int(parameters.get("mel_bins", 64))
            n_fft = int(parameters.get("n_fft", 1024))
            hop_length = int(parameters.get("hop_length", 256))
            freq_mask_param = int(parameters.get("频谱遮挡最大宽度", 10))
            time_mask_param = int(parameters.get("时间遮挡最大长度", 20))
            num_freq_masks = int(parameters.get("频谱遮挡次数", 1))
            num_time_masks = int(parameters.get("时间遮挡次数", 1))
            n_iter = int(parameters.get("反演迭代次数", 16))

            augmented_channels = []
            for c in range(y.shape[0]):
                yc = y[c]
                S = librosa.feature.melspectrogram(
                    y=yc,
                    sr=sr,
                    n_fft=n_fft,
                    hop_length=hop_length,
                    n_mels=n_mels,
                    power=2.0,
                )  # (n_mels, t_frames)
                S_masked = S.copy()

                # 频率遮挡
                for _ in range(max(0, num_freq_masks)):
                    f = int(np.random.uniform(0, max(1, freq_mask_param)))
                    if f <= 0:
                        continue
                    f0 = int(np.random.randint(0, max(1, n_mels - f + 1)))
                    S_masked[f0 : f0 + f, :] = 0.0

                # 时间遮挡
                t_frames = S_masked.shape[-1]
                for _ in range(max(0, num_time_masks)):
                    tt = int(np.random.uniform(0, max(1, time_mask_param)))
                    if tt <= 0:
                        continue
                    t0 = int(np.random.randint(0, max(1, t_frames - tt + 1)))
                    S_masked[:, t0 : t0 + tt] = 0.0

                yc_aug = librosa.feature.inverse.mel_to_audio(
                    S_masked,
                    sr=sr,
                    n_fft=n_fft,
                    hop_length=hop_length,
                    power=2.0,
                    n_iter=n_iter,
                )
                yc_aug = self._match_length(yc_aug[np.newaxis, :], T)[0]
                augmented_channels.append(yc_aug)

            y_out = np.stack(augmented_channels, axis=0)
            output_path = os.path.join(output_dir, f"specaugment_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_filter_processing_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """频域增强 6：滤波处理（FFT 频带置零）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            filter_type = str(parameters.get("滤波类型", "bandpass")).lower()
            low_hz = float(parameters.get("低截止频率Hz", 300.0))
            high_hz = float(parameters.get("高截止频率Hz", 3000.0))
            low_hz = max(0.0, low_hz)
            high_hz = max(0.0, high_hz)
            if low_hz > high_hz:
                low_hz, high_hz = high_hz, low_hz

            y_out_channels = []
            for c in range(y.shape[0]):
                yc = y[c]
                n = len(yc)
                Y = np.fft.rfft(yc)
                freqs = np.fft.rfftfreq(n, d=1.0 / sr)

                mask = np.ones_like(Y, dtype=np.float32)
                if filter_type == "lowpass":
                    mask[freqs > high_hz] = 0.0
                elif filter_type == "highpass":
                    mask[freqs < low_hz] = 0.0
                elif filter_type == "bandstop":
                    mask[(freqs >= low_hz) & (freqs <= high_hz)] = 0.0
                else:
                    # bandpass 默认
                    mask[(freqs < low_hz) | (freqs > high_hz)] = 0.0

                Yf = Y * mask
                yf = np.fft.irfft(Yf, n=n)
                yf = self._match_length(yf[np.newaxis, :], T)[0]
                y_out_channels.append(yf)

            y_out = np.stack(y_out_channels, axis=0)
            output_path = os.path.join(output_dir, f"filter_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_environment_noise_injection_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """环境噪声增强 7：噪声注入（随机噪声叠加/环境噪声近似）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            noise_type = str(parameters.get("噪声类型", "white")).lower()
            snr_db = float(parameters.get("目标SNR分贝", 10.0))
            snr_db = max(-5.0, min(snr_db, 60.0))

            rng = np.random.default_rng()
            y_out_channels = []
            for c in range(y.shape[0]):
                signal = y[c]
                noise = rng.standard_normal(size=T).astype(np.float32)
                if noise_type == "pink":
                    noise = np.cumsum(noise) / (np.sqrt(np.arange(1, T + 1, dtype=np.float32)) + 1e-6)
                elif noise_type == "brown":
                    noise = np.cumsum(noise)
                    noise = noise / (np.max(np.abs(noise)) + 1e-6)
                elif noise_type == "uniform":
                    noise = rng.uniform(-1.0, 1.0, size=T).astype(np.float32)
                # 其他类型默认当作 white

                # 按目标 SNR 缩放噪声
                sp = float(np.mean(signal.astype(np.float32) ** 2) + 1e-8)
                npow = float(np.mean(noise.astype(np.float32) ** 2) + 1e-8)
                snr_linear = 10.0 ** (snr_db / 10.0)
                noise_scale = np.sqrt(sp / (snr_linear * npow))
                y_noisy = signal + noise_scale * noise
                y_noisy = self._match_length(y_noisy[np.newaxis, :], T)[0]
                y_out_channels.append(y_noisy)

            y_out = np.stack(y_out_channels, axis=0)
            output_path = os.path.join(output_dir, f"env_noise_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_spatial_acoustics_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """环境噪声增强 8：空间声学（混响/回声）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            # 回声
            echo_prob = float(parameters.get("回声概率", 0.5))
            num_echoes = int(parameters.get("回声次数", 3))
            min_delay_sec = float(parameters.get("最小回声延迟秒", 0.02))
            max_delay_sec = float(parameters.get("最大回声延迟秒", 0.08))
            echo_decay = float(parameters.get("回声衰减系数", 0.5))

            # 混响
            reverb_prob = float(parameters.get("混响概率", 0.5))
            reverb_prob = max(0.0, min(reverb_prob, 1.0))
            reverb_duration_sec = float(parameters.get("混响持续秒", 0.6))
            reverb_decay = float(parameters.get("混响衰减tau", 0.2))  # 指数衰减时间常数（秒）

            y_out_channels = []
            for c in range(y.shape[0]):
                yc = y[c].astype(np.float32)
                y_aug = yc.copy()

                # 回声：多次延迟叠加
                if np.random.rand() < echo_prob:
                    num_echoes_eff = max(1, num_echoes)
                    for k in range(num_echoes_eff):
                        delay_sec = float(np.random.uniform(min_delay_sec, max_delay_sec))
                        delay = int(delay_sec * sr)
                        if delay <= 0:
                            continue
                        decay = (echo_decay ** k)
                        delayed = np.zeros_like(y_aug)
                        if delay < T:
                            delayed[delay:] = y_aug[: T - delay]
                        y_aug = y_aug + decay * delayed

                # 混响：卷积生成简单房间冲激响应
                if np.random.rand() < reverb_prob:
                    L = int(max(1, reverb_duration_sec * sr))
                    t = np.arange(L, dtype=np.float32) / sr
                    # 生成指数衰减 + 随机噪声的 IR
                    ir = (np.random.randn(L).astype(np.float32) * np.exp(-t / (reverb_decay + 1e-6)))
                    # 卷积后裁剪到原长度
                    y_conv = np.convolve(y_aug, ir, mode="full")
                    y_aug = y_conv[:T]

                y_aug = self._match_length(y_aug[np.newaxis, :], T)[0]
                y_out_channels.append(y_aug)

            y_out = np.stack(y_out_channels, axis=0)
            output_path = os.path.join(output_dir, f"spatial_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_quality_distortion_transformation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """环境噪声增强 9：质感与失真（带宽限制/量化/饱和失真）。"""
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            downsample_ratio = float(parameters.get("降采样比例", 0.8))  # 0.4~1.0
            downsample_ratio = max(0.2, min(downsample_ratio, 1.0))
            bits = int(parameters.get("量化位深", 8))  # 4~16
            bits = max(2, min(bits, 16))
            drive = float(parameters.get("失真驱动强度", 0.0))  # 0~?
            drive = max(0.0, drive)

            y_out_channels = []
            for c in range(y.shape[0]):
                yc = y[c].astype(np.float32)

                # 1) 带宽限制：降采样再上采样
                if downsample_ratio < 0.999:
                    new_sr = int(sr * downsample_ratio)
                    new_sr = max(8000, new_sr) if sr > 0 else new_sr
                    yc_ds = librosa.resample(yc, orig_sr=sr, target_sr=new_sr)
                    yc_up = librosa.resample(yc_ds, orig_sr=new_sr, target_sr=sr)
                    yc = self._match_length(yc_up[np.newaxis, :], T)[0]

                # 2) Bitcrush：量化
                levels = (2 ** bits) - 1
                yc = np.round(yc * levels) / levels

                # 3) 非线性饱和：模拟廉价音频链路失真
                if drive > 0.0:
                    # 使用 tanh 做软削波；drive 越大越明显
                    yc = np.tanh(drive * yc) / (np.tanh(drive) + 1e-6)

                yc = self._match_length(yc[np.newaxis, :], T)[0]
                y_out_channels.append(yc)

            y_out = np.stack(y_out_channels, axis=0)
            output_path = os.path.join(output_dir, f"distort_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def apply_composite_audio_augmentation(
        self,
        audio_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """复合增强 10：组合策略

        从多个增强类别中随机抽取若干个按序串联，提升复杂度与多样性。
        """
        try:
            if sf is None or librosa is None:
                return None
            loaded = self._load_audio(audio_path)
            if loaded is None:
                return None
            y, sr = loaded
            T = y.shape[-1]

            combo_times = int(parameters.get("组合次数", 3))
            combo_times = max(2, min(combo_times, 6))
            include_specaugment = bool(parameters.get("是否包含SpecAugment", True))
            include_spatial = bool(parameters.get("是否包含空间声学", True))

            rng = np.random.default_rng()
            y_out = y.copy()

            # 候选操作（优先选择相对轻量、可控的）
            candidate_ops = [
                "tempo_pitch",
                "energy",
                "timeseries",
                "channel",
                "noise",
                "filter",
                "distort",
            ]
            if include_specaugment:
                candidate_ops.append("specaugment")
            if include_spatial:
                candidate_ops.append("spatial")

            ops = rng.choice(candidate_ops, size=min(combo_times, len(candidate_ops)), replace=False)

            for op in ops:
                if op == "tempo_pitch":
                    rate = float(parameters.get("复合时间拉伸速率", rng.uniform(0.9, 1.1)))
                    n_steps = float(parameters.get("复合音高半音偏移", rng.uniform(-2, 2)))
                    # time stretch
                    if rate > 0 and abs(rate - 1.0) > 1e-6:
                        stretched = []
                        for c in range(y_out.shape[0]):
                            yt = librosa.effects.time_stretch(y_out[c], rate=rate)
                            yt = self._match_length(yt[np.newaxis, :], T)[0]
                            stretched.append(yt)
                        y_out = np.stack(stretched, axis=0)
                    # pitch shift
                    if abs(n_steps) > 1e-6:
                        pitched = []
                        for c in range(y_out.shape[0]):
                            yp = librosa.effects.pitch_shift(y_out[c], sr=sr, n_steps=n_steps)
                            yp = self._match_length(yp[np.newaxis, :], T)[0]
                            pitched.append(yp)
                        y_out = np.stack(pitched, axis=0)
                elif op == "energy":
                    gain = float(parameters.get("复合音量缩放", rng.uniform(0.7, 1.3)))
                    y_out = y_out * gain
                    # 少量静音
                    if rng.random() < 0.7:
                        silence_start = int(rng.integers(0, max(1, T - int(0.1 * sr))))
                        silence_len = int(rng.uniform(0.02, 0.08) * sr)
                        silence_len = max(1, min(silence_len, T - silence_start))
                        y_out[:, silence_start : silence_start + silence_len] = 0.0
                elif op == "timeseries":
                    # shift 或 reverse
                    if rng.random() < 0.5:
                        shift_sec = float(rng.uniform(-0.2, 0.2))
                        shift = int(shift_sec * sr)
                        if shift != 0:
                            out = np.zeros_like(y_out)
                            if shift > 0:
                                out[:, shift:] = y_out[:, : T - shift]
                            else:
                                s = -shift
                                out[:, : T - s] = y_out[:, s:]
                            y_out = out
                    if rng.random() < 0.3:
                        y_out = y_out[:, ::-1].copy()
                elif op == "channel":
                    # 随机 mono/stereo
                    target_channels = "mono" if rng.random() < 0.5 else "stereo"
                    if target_channels == "mono":
                        if y_out.shape[0] > 1:
                            y_out = np.mean(y_out, axis=0, keepdims=True)
                    else:
                        if y_out.shape[0] == 1:
                            ch1 = y_out[0]
                            ch2 = ch1 * (1.0 + rng.uniform(-0.002, 0.002))
                            y_out = np.stack([ch1, ch2], axis=0)
                        else:
                            y_out = y_out[:2]
                elif op == "noise":
                    snr_db = float(parameters.get("复合目标SNR分贝", rng.uniform(5.0, 20.0)))
                    noise_type = str(parameters.get("复合噪声类型", "white"))
                    y_noisy_channels = []
                    for c in range(y_out.shape[0]):
                        signal = y_out[c]
                        noise = rng.standard_normal(size=T).astype(np.float32)
                        if noise_type == "pink":
                            noise = np.cumsum(noise) / (np.sqrt(np.arange(1, T + 1, dtype=np.float32)) + 1e-6)
                        elif noise_type == "brown":
                            noise = np.cumsum(noise)
                            noise = noise / (np.max(np.abs(noise)) + 1e-6)
                        sp = float(np.mean(signal.astype(np.float32) ** 2) + 1e-8)
                        npow = float(np.mean(noise.astype(np.float32) ** 2) + 1e-8)
                        snr_linear = 10.0 ** (snr_db / 10.0)
                        noise_scale = np.sqrt(sp / (snr_linear * npow))
                        y_noisy_channels.append(signal + noise_scale * noise)
                    y_out = np.stack(y_noisy_channels, axis=0)
                elif op == "filter":
                    low_hz = float(parameters.get("复合低截止频率Hz", rng.uniform(200, 800)))
                    high_hz = float(parameters.get("复合高截止频率Hz", rng.uniform(1500, 4000)))
                    if low_hz > high_hz:
                        low_hz, high_hz = high_hz, low_hz
                    # bandpass
                    y_f_channels = []
                    for c in range(y_out.shape[0]):
                        yc = y_out[c]
                        n = len(yc)
                        Y = np.fft.rfft(yc)
                        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
                        mask = np.ones_like(Y, dtype=np.float32)
                        mask[(freqs < low_hz) | (freqs > high_hz)] = 0.0
                        yf = np.fft.irfft(Y * mask, n=n)
                        y_f_channels.append(self._match_length(yf[np.newaxis, :], T)[0])
                    y_out = np.stack(y_f_channels, axis=0)
                elif op == "distort":
                    downsample_ratio = float(parameters.get("复合降采样比例", rng.uniform(0.6, 0.95)))
                    bits = int(parameters.get("复合量化位深", rng.integers(6, 12)))
                    # 仅做降采样 + 量化
                    bits = max(2, min(bits, 16))
                    y_d_channels = []
                    for c in range(y_out.shape[0]):
                        yc = y_out[c].astype(np.float32)
                        if downsample_ratio < 0.999:
                            new_sr = int(sr * downsample_ratio)
                            new_sr = max(8000, new_sr)
                            yc_ds = librosa.resample(yc, orig_sr=sr, target_sr=new_sr)
                            yc_up = librosa.resample(yc_ds, orig_sr=new_sr, target_sr=sr)
                            yc = self._match_length(yc_up[np.newaxis, :], T)[0]
                        levels = (2 ** bits) - 1
                        yc = np.round(yc * levels) / levels
                        y_d_channels.append(self._match_length(yc[np.newaxis, :], T)[0])
                    y_out = np.stack(y_d_channels, axis=0)
                elif op == "specaugment":
                    # SpecAugment 会较耗时；此处用较小参数
                    n_mels = int(parameters.get("复合SpecAugment_mel_bins", 48))
                    n_fft = int(parameters.get("复合SpecAugment_n_fft", 1024))
                    hop_length = int(parameters.get("复合SpecAugment_hop_length", 256))
                    freq_mask_param = int(parameters.get("复合SpecAugment_freq_mask", 8))
                    time_mask_param = int(parameters.get("复合SpecAugment_time_mask", 16))
                    n_iter = int(parameters.get("复合SpecAugment反演迭代", 12))
                    aug_channels = []
                    for c in range(y_out.shape[0]):
                        yc = y_out[c]
                        S = librosa.feature.melspectrogram(
                            y=yc,
                            sr=sr,
                            n_fft=n_fft,
                            hop_length=hop_length,
                            n_mels=n_mels,
                            power=2.0,
                        )
                        S_masked = S.copy()
                        # 1-2 次遮挡
                        for _ in range(1 + int(rng.random() < 0.5)):
                            f = int(rng.uniform(0, max(1, freq_mask_param)))
                            if f > 0:
                                f0 = int(rng.integers(0, max(1, n_mels - f + 1)))
                                S_masked[f0 : f0 + f, :] = 0.0
                        t_frames = S_masked.shape[-1]
                        for _ in range(1 + int(rng.random() < 0.5)):
                            tt = int(rng.uniform(0, max(1, time_mask_param)))
                            if tt > 0:
                                t0 = int(rng.integers(0, max(1, t_frames - tt + 1)))
                                S_masked[:, t0 : t0 + tt] = 0.0

                        yc_aug = librosa.feature.inverse.mel_to_audio(
                            S_masked,
                            sr=sr,
                            n_fft=n_fft,
                            hop_length=hop_length,
                            power=2.0,
                            n_iter=n_iter,
                        )
                        aug_channels.append(self._match_length(yc_aug[np.newaxis, :], T)[0])
                    y_out = np.stack(aug_channels, axis=0)
                elif op == "spatial":
                    # echo + 简单 reverb（轻量版）
                    echo_prob = float(parameters.get("复合回声概率", 0.5))
                    reverb_prob = float(parameters.get("复合混响概率", 0.4))
                    num_echoes = int(parameters.get("复合回声次数", 2))
                    min_delay_sec = float(parameters.get("复合回声最小延迟秒", 0.02))
                    max_delay_sec = float(parameters.get("复合回声最大延迟秒", 0.06))
                    echo_decay = float(parameters.get("复合回声衰减系数", 0.5))
                    reverb_duration_sec = float(parameters.get("复合混响持续秒", 0.5))
                    reverb_decay = float(parameters.get("复合混响tau", 0.2))

                    out_channels = []
                    for c in range(y_out.shape[0]):
                        yc = y_out[c]
                        y_aug = yc.copy()
                        if rng.random() < echo_prob:
                            for k in range(max(1, num_echoes)):
                                delay = int(float(rng.uniform(min_delay_sec, max_delay_sec)) * sr)
                                if delay <= 0:
                                    continue
                                decay = echo_decay ** k
                                delayed = np.zeros_like(y_aug)
                                if delay < T:
                                    delayed[delay:] = y_aug[: T - delay]
                                y_aug = y_aug + decay * delayed
                        if rng.random() < reverb_prob:
                            L = int(max(1, reverb_duration_sec * sr))
                            t = np.arange(L, dtype=np.float32) / sr
                            ir = np.random.randn(L).astype(np.float32) * np.exp(-t / (reverb_decay + 1e-6))
                            y_conv = np.convolve(y_aug, ir, mode="full")
                            y_aug = y_conv[:T]
                        out_channels.append(self._match_length(y_aug[np.newaxis, :], T)[0])
                    y_out = np.stack(out_channels, axis=0)

            output_path = os.path.join(output_dir, f"composite_audio_{index}.wav")
            return self._save_audio(y_out, sr, output_path)
        except Exception:
            return None

    def replace_synonyms(self, text_path: str, parameters: Dict[str, Any],
                       output_dir: str, index: int) -> Optional[str]:
        """替换同义词"""
        try:
            # 读取文本
            with open(text_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            
            # 简单的同义词字典
            synonyms = {
                '好': ['优秀', '良好', '出色'],
                '坏': ['糟糕', '差', '恶劣'],
                '大': ['巨大', '庞大', '大型'],
                '小': ['微小', '细小', '小型'],
                '快': ['迅速', '快速', '敏捷'],
                '慢': ['缓慢', '迟缓', '低速']
            }
            
            # 替换比例
            replace_ratio = parameters.get('替换比例', 0.3)
            
            # 分词并替换同义词
            words = re.findall(r'\b\w+\b', text)
            new_words = []
            
            for word in words:
                if word in synonyms and np.random.random() < replace_ratio:
                    # 随机选择一个同义词
                    new_word = np.random.choice(synonyms[word])
                    new_words.append(new_word)
                else:
                    new_words.append(word)
            
            # 重新组合文本
            new_text = ' '.join(new_words)
            
            # 保存结果
            output_path = os.path.join(output_dir, f"synonyms_{index}.txt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(new_text)
            return output_path
        except Exception:
            return None

    def back_translate(self, text_path: str, parameters: Dict[str, Any], 
                      output_dir: str, index: int) -> Optional[str]:
        """回译增强"""
        try:
            # 读取文本
            with open(text_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            
            # 伪回译增强：
            # - 不依赖外部翻译 API/Transformer（后端仅用轻量词表规则）
            # - 思路：中文->英文（替换常见词/短语）->中文（再替换）
            # - 目标：在“尽量保持语义”的前提下产生表述多样性
            #
            # 注意：由于缺少词性标注/大模型语义约束，这里是规则版“回译模拟”，
            # 可跑通流程并提供多样性；如果后续你们环境允许接入 transformers，
            # 我可以再把 4. 上下文与嵌入、5. 生成与风格控制升级为模型版。
            mid_lang = str(parameters.get("中间语言", "en")).lower()
            back_trans_prob = float(parameters.get("回译概率", 1.0))
            back_trans_prob = max(0.0, min(back_trans_prob, 1.0))

            if mid_lang != "en" or np.random.rand() > back_trans_prob:
                transformed_text = text
            else:
                # 1) 中文->英文（词表映射；尽量选择“常见同义表达”）
                zh2en = {
                    "好": ["good", "great"],
                    "坏": ["bad", "poor"],
                    "优秀": ["excellent", "great"],
                    "良好": ["good", "fine"],
                    "出色": ["excellent", "outstanding"],
                    "差": ["bad", "poor"],
                    "恶劣": ["bad", "awful"],
                    "大": ["big", "large"],
                    "巨大": ["huge", "massive"],
                    "大型": ["large-scale", "big"],
                    "小": ["small", "tiny"],
                    "微小": ["tiny", "minute"],
                    "小型": ["small-scale", "small"],
                    "快": ["fast", "quick"],
                    "迅速": ["rapid", "quick"],
                    "快速": ["quick", "rapid"],
                    "敏捷": ["agile"],
                    "慢": ["slow", "sluggish"],
                    "缓慢": ["slow", "gradual"],
                    "迟缓": ["slow", "delayed"],
                    "低速": ["low-speed"],
                    # 一些短语级映射（用于提升表达多样性）
                    "提升": ["improve", "enhance"],
                    "增强": ["enhance", "boost"],
                    "鲁棒性": ["robustness", "reliability"],
                    "泛化": ["generalization"],
                    "保持": ["maintain", "preserve"],
                }

                # 2) 英文->中文（逆向词表；仍是“伪回译”）
                en2zh = {}
                for zh, ens in zh2en.items():
                    for en in ens:
                        en2zh.setdefault(en, []).append(zh)

                # 为了能解析英文 token：用简单空格分隔注入英文词
                # 中文文本可能没有空格，因此我们在替换时才插入空格。
                def _zh_to_en(s: str) -> str:
                    # 长度优先：先替换长短语，避免被短词“截断”
                    keys = sorted(zh2en.keys(), key=len, reverse=True)
                    out = s
                    for k in keys:
                        if k in out and np.random.rand() < 1.0:
                            candidates = zh2en[k]
                            repl = str(np.random.choice(candidates))
                            out = out.replace(k, f" {repl} ")
                    # 合并多余空格
                    out = re.sub(r"\s+", " ", out).strip()
                    return out

                def _en_to_zh(s: str) -> str:
                    # 抓取英文连续字符 token
                    tokens = re.findall(r"[A-Za-z]+|[^A-Za-z]+", s)
                    new_tokens = []
                    for tok in tokens:
                        if re.fullmatch(r"[A-Za-z]+", tok or ""):
                            tok_l = tok.lower()
                            if tok_l in en2zh:
                                zh_choices = en2zh[tok_l]
                                new_tokens.append(str(np.random.choice(zh_choices)))
                            else:
                                # 不在词表里的英文 token，尽量不动
                                new_tokens.append(tok)
                        else:
                            new_tokens.append(tok)
                    joined = "".join(new_tokens)
                    # 去除英文词之间多余空格：尽量保持中文连续
                    joined = re.sub(r"\s+", "", joined)
                    return joined

                en_text = _zh_to_en(text)
                transformed_text = _en_to_zh(en_text)

            # 轻量“句式重构”：按逗号/分号切分后做局部交换，增加表达变化
            reconstruct_ratio = float(parameters.get("句式重构强度", 0.3))
            reconstruct_ratio = max(0.0, min(reconstruct_ratio, 1.0))
            if np.random.rand() < reconstruct_ratio:
                # 以中文常见分隔符切分（尽量不破坏标点结构）
                parts = re.split(r"(，|；|。|！|？)", transformed_text)
                # parts: [text, sep, text, sep, ...]
                # 只在有足够片段时重排文本片段（不动分隔符）
                text_idxs = [i for i in range(0, len(parts)) if i % 2 == 0]
                if len(text_idxs) >= 3:
                    # 只打乱中间片段，保留首尾以降低语义破坏概率
                    parts = re.split(r"(，|；|。|！|？)", transformed_text)
                    text_segs = [parts[i] for i in text_idxs]
                    first, last = text_segs[0], text_segs[-1]
                    mid_segs = text_segs[1:-1]
                    np.random.shuffle(mid_segs)
                    new_text_segs = [first] + mid_segs + [last]
                    for idx, seg in zip(text_idxs, new_text_segs):
                        parts[idx] = seg
                    transformed_text = "".join(parts)

            # 保存结果
            output_path = os.path.join(output_dir, f"backtranslate_{index}.txt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(transformed_text)
            return output_path
        except Exception:
            return None

    # =========================
    # 文本增强（规则+词表版）
    # =========================
    def apply_vocabulary_phrase_substitution(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """基于规则与词汇替换（词汇/短语级，同义词替换，支持“粗粒度词性约束”）。"""
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            # 参数
            replace_ratio = float(parameters.get("替换比例", 0.3))
            replace_ratio = max(0.0, min(replace_ratio, 1.0))
            pos_constraint = str(parameters.get("词性约束", "无")).strip()
            enable_phrase = bool(parameters.get("是否短语级替换", True))

            # 词表（单字同义词：作为简化的词汇级替换）
            # pos_constraint 不做真实 POS 标注，而是用“词表归类”实现粗约束：
            # 只有当 key 在指定词性的词表里，才允许替换。
            synonyms_pos = {
                "无": {
                    "好": ["优秀", "良好", "出色"],
                    "坏": ["糟糕", "差", "恶劣"],
                    "大": ["巨大", "庞大", "大型"],
                    "小": ["微小", "细小", "小型"],
                    "快": ["迅速", "快速", "敏捷"],
                    "慢": ["缓慢", "迟缓", "低速"],
                },
                "形容词": {
                    "好": ["优秀", "良好", "出色"],
                    "坏": ["糟糕", "差", "恶劣"],
                    "大": ["巨大", "庞大", "大型"],
                    "小": ["微小", "细小", "小型"],
                    "快": ["迅速", "快速", "敏捷"],
                    "慢": ["缓慢", "迟缓", "低速"],
                },
                # 由于缺少词性标注器，这里将其余词性映射为“同一词表”
                # 让约束可跑通流程；后续可接入词性标注再细化。
                "名词": {},
                "动词": {},
                "副词": {},
            }
            pos_dict = synonyms_pos.get(pos_constraint, synonyms_pos["无"])
            if not pos_dict:
                pos_dict = synonyms_pos["无"]

            # 短语级同义替换（长短语优先，减少被“局部截断”）
            phrase_synonyms_pos = {
                "无": {
                    "提升": ["增强", "改进"],
                    "增强": ["提升", "加固"],
                    "鲁棒性": ["可靠性", "适应性"],
                    "泛化": ["泛化能力", "推广"],
                    "保持": ["维持", "维系"],
                }
            }
            if enable_phrase:
                phrase_dict = phrase_synonyms_pos.get(pos_constraint, phrase_synonyms_pos["无"])
            else:
                phrase_dict = {}

            # 执行短语替换
            out = text
            if enable_phrase and phrase_dict:
                keys = sorted(phrase_dict.keys(), key=len, reverse=True)
                for k in keys:
                    if k in out and np.random.rand() < replace_ratio:
                        out = out.replace(k, str(np.random.choice(phrase_dict[k])))

            # 执行词汇/字符级替换
            for k, candidates in pos_dict.items():
                if k in out and np.random.rand() < replace_ratio:
                    out = out.replace(k, str(np.random.choice(candidates)))

            output_path = os.path.join(output_dir, f"vocab_phrase_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(out)
            return output_path
        except Exception:
            return None

    def apply_structure_noise_perturbation(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """结构与噪声扰动：随机插入/删除、随机交换、字符级规则扰动。"""
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            if not text:
                return None

            strength = float(parameters.get("扰动强度", 0.1))
            strength = max(0.0, min(strength, 1.0))

            # 每次操作数量大致与长度成正比
            op_count = int(max(1, len(text) * strength))

            chars = list(text)
            insert_pool = list("的一是在不了有和人这中大为上个国我以要到时由业也能下去向你")
            insert_pool += list("，。！？；：、 ")
            insert_pool = [c for c in insert_pool if c.strip() != ""]

            digit_map = {"0": ["O"], "1": ["l"], "2": ["Z"], "3": ["E"], "4": ["A"], "5": ["S"], "6": ["G"], "7": ["T"], "8": ["B"], "9": ["g"]}

            for _ in range(op_count):
                p = np.random.rand()
                if len(chars) <= 1:
                    break

                if p < 0.25:
                    # 删除
                    del_idx = int(np.random.randint(0, len(chars)))
                    # 避免删除太多导致空串：至少保留 1 个字符
                    if len(chars) > 1:
                        del chars[del_idx]
                elif p < 0.50:
                    # 插入
                    ins_idx = int(np.random.randint(0, len(chars)))
                    ins_char = str(np.random.choice(insert_pool))
                    chars.insert(ins_idx, ins_char)
                elif p < 0.75:
                    # 交换相邻字符
                    i = int(np.random.randint(0, len(chars) - 1))
                    chars[i], chars[i + 1] = chars[i + 1], chars[i]
                else:
                    # 字符级规则扰动：数字/字母相似替换，或轻微符号扰动
                    i = int(np.random.randint(0, len(chars)))
                    c = chars[i]
                    if c in digit_map and np.random.rand() < 0.5:
                        chars[i] = str(np.random.choice(digit_map[c]))
                    elif c in "，。！？；：":
                        punct_map = {"，": "、", "。": "！", "！": "。", "？": "！", "；": "，", "：": "；"}
                        chars[i] = punct_map.get(c, c)
                    else:
                        # 随机空格扰动
                        if np.random.rand() < 0.3:
                            chars.insert(i, " ")

            out = "".join(chars)
            output_path = os.path.join(output_dir, f"noise_perturb_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(out)
            return output_path
        except Exception:
            return None

    def apply_context_and_embedding_transformation(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """基于上下文与嵌入（规则版上下文约束替换 + 伪跨语言增强）。"""
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            if not text:
                return None

            # 词表候选：沿用 1. 中的同义词（简化版）
            synonyms = {
                "好": ["优秀", "良好", "出色"],
                "坏": ["糟糕", "差", "恶劣"],
                "大": ["巨大", "庞大", "大型"],
                "小": ["微小", "细小", "小型"],
                "快": ["迅速", "快速", "敏捷"],
                "慢": ["缓慢", "迟缓", "低速"],
            }

            mask_ratio = float(parameters.get("mask比例", 0.1))
            mask_ratio = max(0.0, min(mask_ratio, 1.0))
            cross_lang_strength = float(parameters.get("跨语言增强强度", 0.0))
            cross_lang_strength = max(0.0, min(cross_lang_strength, 1.0))

            # 计算字符二元组频次（作为轻量“上下文语言模型”）
            cleaned = re.sub(r"\s+", "", text)
            bigram_counts: Dict[str, int] = {}
            for i in range(len(cleaned) - 1):
                bg = cleaned[i : i + 2]
                bigram_counts[bg] = bigram_counts.get(bg, 0) + 1
            total = max(1, sum(bigram_counts.values()))

            def _score_boundary(left_char: str, right_char: str, mid: str) -> float:
                # 只用替换片段内部二元组 + 替换边界二元组，局部评分
                s = 0.0
                if left_char and mid:
                    s += np.log((bigram_counts.get(left_char + mid[0], 0) + 1) / (total + 1))
                for j in range(len(mid) - 1):
                    s += np.log((bigram_counts.get(mid[j : j + 2], 0) + 1) / (total + 1))
                if mid and right_char:
                    s += np.log((bigram_counts.get(mid[-1] + right_char, 0) + 1) / (total + 1))
                return float(s)

            # 将 text 作为字符序列，尽量保留空白
            out = list(text)
            # 找到可替换位置：这里按“单字 key”处理
            candidate_positions = [i for i, ch in enumerate(out) if ch in synonyms]
            if not candidate_positions:
                return None

            num_to_mask = max(1, int(len(candidate_positions) * mask_ratio))
            np.random.shuffle(candidate_positions)
            selected = candidate_positions[:num_to_mask]

            for pos in selected:
                key = out[pos]
                candidates = synonyms[key]
                # 当前替换左右邻居（非空白字符邻居更稳定）
                left = None
                for li in range(pos - 1, -1, -1):
                    if out[li] not in [" ", "\n", "\t", "\r"]:
                        left = out[li]
                        break
                right = None
                for ri in range(pos + 1, len(out)):
                    if out[ri] not in [" ", "\n", "\t", "\r"]:
                        right = out[ri]
                        break

                best = key
                best_score = -1e18
                for cand in candidates:
                    # 简单约束：替换后不为空；并计算局部二元组得分
                    if not cand:
                        continue
                    sc = _score_boundary(left or "", right or "", cand)
                    if sc > best_score:
                        best_score = sc
                        best = cand

                # 可选：伪跨语言增强（小概率对 best 再做“回译风格”的二次变体）
                if cross_lang_strength > 0 and np.random.rand() < cross_lang_strength:
                    # 用极简英->中词表增强：映射到英文同义词再映射回来
                    # 若 best 不在表内则保持不变
                    zh2en_simple = {"优秀": "excellent", "良好": "good", "出色": "outstanding", "糟糕": "bad", "差": "poor", "恶劣": "awful", "巨大": "huge", "庞大": "massive", "大型": "large", "微小": "tiny", "细小": "minute", "小型": "small", "迅速": "rapid", "快速": "quick", "敏捷": "agile", "缓慢": "slow", "迟缓": "delayed", "低速": "low-speed"}
                    en2zh_simple = {}
                    for zh, en in zh2en_simple.items():
                        en2zh_simple.setdefault(en, []).append(zh)
                    en = zh2en_simple.get(best)
                    if en and en in en2zh_simple:
                        best = str(np.random.choice(en2zh_simple[en]))

                out[pos] = best

            out_text = "".join(out)
            output_path = os.path.join(output_dir, f"context_embed_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(out_text)
            return output_path
        except Exception:
            return None

    def apply_style_controlled_generation(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """生成与风格控制（规则版可控改写：正式/口语/简洁）。"""
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            if not text:
                return None

            style = str(parameters.get("风格标签", "正式")).strip()
            style = style if style else "正式"

            concise_strength = float(parameters.get("简洁强度", 0.5))
            concise_strength = max(0.0, min(concise_strength, 1.0))

            out = text

            if style in ("正式", "学术"):
                # 正式化替换（轻量词表）
                rep = {
                    "搞": "进行",
                    "挺": "相当",
                    "很": "较为",
                    "非常": "十分",
                    "特别": "尤其",
                    "可能": "或许",
                    "感觉": "认为",
                }
                for a, b in rep.items():
                    if a in out and np.random.rand() < 0.8:
                        out = out.replace(a, b)
                # 加一点礼貌性收束
                if "。" in out or "！" in out or "？" in out:
                    if np.random.rand() < 0.5:
                        out = out + "（以上为初步表述。）"
            elif style in ("口语", "随意"):
                rep = {
                    "进行": "搞",
                    "相当": "挺",
                    "较为": "挺",
                    "十分": "很",
                    "尤其": "特别",
                    "或许": "可能",
                    "认为": "觉得",
                }
                for a, b in rep.items():
                    if a in out and np.random.rand() < 0.8:
                        out = out.replace(a, b)
                # 口语助词
                if np.random.rand() < 0.5:
                    out = out.replace("，", "，真的，")
            elif style in ("简洁", "精简"):
                # 删掉冗余表达
                drop_phrases = ["其实", "可能", "感觉", "大概", "大致", "非常", "真的", "挺"]
                for p in drop_phrases:
                    if p in out and np.random.rand() < concise_strength:
                        out = out.replace(p, "")
                # 过长句式简化：把“并且/同时”改成“且”
                out = out.replace("并且", "且").replace("同时", "且")
            else:
                # 未识别风格：不做强改动
                pass

            output_path = os.path.join(output_dir, f"style_control_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(out)
            return output_path
        except Exception:
            return None

    def apply_sentence_or_paragraph_reordering(
        self,
        text_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """篇章结构：句子重排/段落重排。"""
        try:
            with open(text_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

            if not text:
                return None

            granularity = str(parameters.get("重排粒度", "句子")).strip()
            shuffle_strength = float(parameters.get("打乱强度", 0.5))
            shuffle_strength = max(0.0, min(shuffle_strength, 1.0))
            keep_first_last = bool(parameters.get("保留首尾", True))

            out = text

            if granularity == "段落":
                # 按空行切段
                blocks = re.split(r"\n\s*\n", text.strip())
                blocks = [b for b in blocks if b.strip()]
                if len(blocks) >= 2:
                    k = int(max(1, len(blocks) * shuffle_strength))
                    idxs = list(range(len(blocks)))
                    np.random.shuffle(idxs)
                    idxs = idxs[:k]
                    if keep_first_last and len(blocks) >= 3:
                        # 保留首尾
                        idxs = [i for i in idxs if i not in (0, len(blocks) - 1)]
                        if not idxs:
                            idxs = [1]
                    new_blocks = blocks[:]
                    shuffled = [blocks[i] for i in idxs]
                    np.random.shuffle(shuffled)
                    for i, b in zip(idxs, shuffled):
                        new_blocks[i] = b
                    out = "\n\n".join(new_blocks)
            else:
                # 句子切分（中文标点）
                # 捕获“句子+终结符”形式：如 "...。"
                sentence_pattern = r"[^。！？!?]+[。！？!?]"
                sentences = re.findall(sentence_pattern, text)
                remainder = re.sub(sentence_pattern, "", text)
                remainder = remainder.strip()
                if remainder:
                    sentences.append(remainder)

                if len(sentences) >= 2:
                    k = int(max(1, len(sentences) * shuffle_strength))
                    idxs = list(range(len(sentences)))
                    np.random.shuffle(idxs)
                    idxs = idxs[:k]
                    if keep_first_last and len(sentences) >= 3:
                        idxs = [i for i in idxs if i not in (0, len(sentences) - 1)]
                        if not idxs:
                            idxs = [1]
                    new_sents = sentences[:]
                    shuffled = [sentences[i] for i in idxs]
                    np.random.shuffle(shuffled)
                    for i, s in zip(idxs, shuffled):
                        new_sents[i] = s
                    out = "".join(new_sents)

            output_path = os.path.join(output_dir, f"reorder_{index}.txt")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(out)
            return output_path
        except Exception:
            return None

    def _read_images_as_tensor(
        self,
        image_paths: List[str],
        image_size: int,
        max_images: int,
        device: torch.device,
    ) -> Optional[torch.Tensor]:
        """把若干张图片读进来并转成张量（N, 3, H, W），归一化到[-1, 1]。

        说明：这里实现的是“轻量级 demo 用”的数据增强生成逻辑，
        训练/采样都会在 CPU 上运行，因此分辨率和样本量都会做上限裁剪。
        """
        if not image_paths:
            return None

        # 为了避免任务数据集过大导致训练耗时爆炸，这里限制最多训练图片数量。
        sampled_paths = image_paths[:max_images]
        tensors: List[torch.Tensor] = []
        for p in sampled_paths:
            img = cv2.imread(p)
            if img is None:
                continue
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = cv2.resize(img, (image_size, image_size), interpolation=cv2.INTER_AREA)
            x = torch.from_numpy(img).permute(2, 0, 1).to(device=device, dtype=torch.float32) / 255.0
            x = x * 2.0 - 1.0  # [-1, 1]
            tensors.append(x)

        if not tensors:
            return None

        return torch.stack(tensors, dim=0)  # (N, 3, H, W)

    def _tensor_to_bgr_image(self, x: torch.Tensor) -> np.ndarray:
        """把生成的张量（3,H,W，值域大致[-1,1]）转成 OpenCV 的 BGR uint8 图像。"""
        x = x.detach().cpu().clamp(-1.0, 1.0)
        x = (x + 1.0) / 2.0  # [0,1]
        x = (x * 255.0).to(torch.uint8)
        x = x.permute(1, 2, 0).numpy()  # HWC, RGB
        x = cv2.cvtColor(x, cv2.COLOR_RGB2BGR)  # 转 BGR 便于 cv2.imwrite
        return x

    # =========================
    # WGAN-GP（深度学习生成增强）
    # =========================
    def train_wgan_gp(
        self,
        training_image_paths: List[str],
        parameters: Dict[str, Any],
        image_size: int = 32,
    ) -> Optional[Dict[str, Any]]:
        """训练一个轻量 WGAN-GP 生成器，并返回可用于生成的上下文。

        参数（来自前端配置的 keys）
        - 梯度惩罚系数：λ（默认 10.0）
        - 判别器迭代次：n_critic（默认 5）
        - 学习率：lr（默认 1e-4）

        重要说明
        - 当前仓库没有提供预训练权重文件，因此这里实现“按任务现场训练”的轻量版本。
        - 为了保证 CPU 可运行，会把图片分辨率裁剪到 `image_size`，并对训练步数做上限裁剪。
        """
        if not self._torch_available():
            return None
        device = torch.device("cpu")
        if len(training_image_paths) < 2:
            return None

        gp_lambda = float(parameters.get("梯度惩罚系数", 10.0))
        n_critic = int(parameters.get("判别器迭代次", 5))
        lr = float(parameters.get("学习率", 1e-4))

        max_images = int(parameters.get("最大训练图片数", 32))
        max_images = max(2, min(max_images, 64))

        images = self._read_images_as_tensor(
            image_paths=training_image_paths,
            image_size=image_size,
            max_images=max_images,
            device=device,
        )
        if images is None or images.size(0) < 2:
            return None

        n = images.size(0)
        batch_size = min(16, n)

        latent_dim = 100
        base_ch = 64

        class Generator(nn.Module):
            def __init__(self):
                super().__init__()
                self.fc = nn.Linear(latent_dim, base_ch * 4 * 4)
                self.net = nn.Sequential(
                    nn.ReLU(inplace=True),
                    nn.ConvTranspose2d(base_ch, base_ch // 2, 4, 2, 1),  # 4 -> 8
                    nn.ReLU(inplace=True),
                    nn.ConvTranspose2d(base_ch // 2, base_ch // 4, 4, 2, 1),  # 8 -> 16
                    nn.ReLU(inplace=True),
                    nn.ConvTranspose2d(base_ch // 4, 3, 4, 2, 1),  # 16 -> 32
                    nn.Tanh(),
                )

            def forward(self, z: torch.Tensor) -> torch.Tensor:
                x = self.fc(z).view(-1, base_ch, 4, 4)
                return self.net(x)

        class Discriminator(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = nn.Sequential(
                    nn.Conv2d(3, base_ch // 4, 4, 2, 1),  # 32 -> 16
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(base_ch // 4, base_ch // 2, 4, 2, 1),  # 16 -> 8
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(base_ch // 2, base_ch, 4, 2, 1),  # 8 -> 4
                    nn.LeakyReLU(0.2, inplace=True),
                )
                self.fc = nn.Linear(base_ch * 4 * 4, 1)

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                h = self.net(x).view(x.size(0), -1)
                return self.fc(h)

        def gradient_penalty(
            d_model: nn.Module,
            x_real: torch.Tensor,
            x_fake: torch.Tensor,
        ) -> torch.Tensor:
            """WGAN-GP 的梯度惩罚项：E[(||∇D(x̂)||2 - 1)^2]"""
            b = x_real.size(0)
            eps = torch.rand(b, 1, 1, 1, device=device)
            x_hat = eps * x_real + (1 - eps) * x_fake
            x_hat.requires_grad_(True)

            d_hat = d_model(x_hat)
            grad = torch.autograd.grad(
                outputs=d_hat,
                inputs=x_hat,
                grad_outputs=torch.ones_like(d_hat),
                create_graph=True,
                retain_graph=True,
                only_inputs=True,
            )[0]

            grad = grad.view(b, -1)
            norm = grad.norm(2, dim=1)
            return ((norm - 1.0) ** 2).mean()

        g = Generator().to(device)
        d = Discriminator().to(device)

        g_opt = optim.Adam(g.parameters(), lr=lr, betas=(0.5, 0.9))
        d_opt = optim.Adam(d.parameters(), lr=lr, betas=(0.5, 0.9))

        # 训练步数上限：按样本量粗略估计，但保证不会无限跑。
        steps = max(5, min(60, n * 2))
        z_fixed = torch.randn(batch_size, latent_dim, device=device)  # 只是帮助 sanity check（不必保存）

        for step in range(steps):
            # --- 判别器更新 ---
            for _ in range(max(1, n_critic)):
                idx = torch.randint(0, n, (batch_size,), device=device)
                x_real = images[idx]
                z = torch.randn(batch_size, latent_dim, device=device)
                x_fake = g(z).detach()

                d_real = d(x_real).mean()
                d_fake = d(x_fake).mean()
                gp = gradient_penalty(d, x_real, x_fake)

                # WGAN-GP: 最大化 d_real - d_fake 等价于最小化 -(d_real - d_fake)
                d_loss = -(d_real - d_fake) + gp_lambda * gp
                d_opt.zero_grad()
                d_loss.backward()
                d_opt.step()

            # --- 生成器更新 ---
            idx = torch.randint(0, n, (batch_size,), device=device)
            _ = idx  # 生成器更新不依赖 x_real，但保留以便未来改成条件 GAN
            z = torch.randn(batch_size, latent_dim, device=device)
            x_fake = g(z)
            g_loss = -d(x_fake).mean()
            g_opt.zero_grad()
            g_loss.backward()
            g_opt.step()

        return {
            "type": "wgan-gp",
            "generator": g,
            "latent_dim": latent_dim,
            "image_size": image_size,
            "device": device,
        }

    def generate_with_wgan_gp_from_context(
        self,
        gan_context: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """使用已训练好的 WGAN-GP generator 生成一张新图片。"""
        try:
            if not self._torch_available():
                return None
            g: nn.Module = gan_context["generator"]
            latent_dim = int(gan_context["latent_dim"])
            image_size = int(gan_context["image_size"])
            device: torch.device = gan_context["device"]

            g.eval()
            with torch.no_grad():
                z = torch.randn(1, latent_dim, device=device)
                x = g(z)[0]  # (3,H,W)

            img_bgr = self._tensor_to_bgr_image(x)
            output_path = os.path.join(output_dir, f"wgan-gp_{index}.jpg")
            # cv2 直接写 BGR
            cv2.imwrite(output_path, img_bgr)
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
        """兼容旧接口：对单张图像做“弱化版 GAN 生成”。

        由于按任务训练需要多张图片，这里如果训练失败就退化到简单的图像扰动（保证流程不中断）。
        """
        try:
            gan_context = self.train_wgan_gp([sample_path], parameters)
            if gan_context is None:
                img = cv2.imread(sample_path)
                if img is None:
                    return None
                img = cv2.flip(img, 1)
                img = cv2.GaussianBlur(img, (5, 5), 0)
                output_path = os.path.join(output_dir, f"gan_{index}.jpg")
                cv2.imwrite(output_path, img)
                return output_path

            return self.generate_with_wgan_gp_from_context(gan_context, output_dir, index)
        except Exception:
            return None

    # =========================
    # Diffusion（深度学习生成增强）
    # =========================
    def train_diffusion(
        self,
        training_image_paths: List[str],
        parameters: Dict[str, Any],
        image_size: int = 32,
        diffusion_steps: int = 200,
    ) -> Optional[Dict[str, Any]]:
        """训练一个轻量 DDPM 噪声预测模型，并返回可用于采样的上下文。

        参数（来自前端配置的 keys）
        - 扩散步数上限：仅影响采样时的推理步数（训练这里用固定 diffusion_steps=200）
        - CFG引导阶数：仅用于采样时对预测噪声的缩放（本实现为“无条件”扩散，CFG 做简化处理）

        为了 CPU 可运行，本实现会把训练图片分辨率裁剪到 `image_size`，并对训练步数做上限。
        """
        if not self._torch_available():
            return None
        device = torch.device("cpu")
        if len(training_image_paths) < 2:
            return None

        # 训练时用固定的时间步数（真实扩散模型会很多步，这里做轻量化）
        T = int(diffusion_steps)
        beta_start = 1e-4
        beta_end = 0.02
        betas = torch.linspace(beta_start, beta_end, T, device=device)
        alphas = 1.0 - betas
        alphas_cumprod = torch.cumprod(alphas, dim=0)

        images = self._read_images_as_tensor(
            image_paths=training_image_paths,
            image_size=image_size,
            max_images=int(parameters.get("最大训练图片数", 32)),
            device=device,
        )
        if images is None or images.size(0) < 2:
            return None

        n = images.size(0)
        batch_size = min(16, n)

        base_ch = 64
        time_dim = 128

        def timestep_embedding(t: torch.Tensor, dim: int) -> torch.Tensor:
            """sin/cos embedding，t: (B,) int64"""
            half = dim // 2
            emb_scale = np.log(10000.0) / (half - 1)
            emb = torch.exp(torch.arange(half, device=device, dtype=torch.float32) * -emb_scale)
            emb = t.float().unsqueeze(1) * emb.unsqueeze(0)
            return torch.cat([torch.sin(emb), torch.cos(emb)], dim=1)  # (B, dim)

        class SimpleNoisePredictor(nn.Module):
            def __init__(self):
                super().__init__()
                self.conv1 = nn.Conv2d(3, base_ch, 3, 1, 1)
                self.conv2 = nn.Conv2d(base_ch, base_ch * 2, 4, 2, 1)  # 32->16
                self.conv3 = nn.Conv2d(base_ch * 2, base_ch * 2, 3, 1, 1)
                self.time_mlp = nn.Sequential(
                    nn.Linear(time_dim, base_ch * 2),
                    nn.ReLU(inplace=True),
                    nn.Linear(base_ch * 2, base_ch * 2),
                )
                self.up = nn.ConvTranspose2d(base_ch * 2, base_ch, 4, 2, 1)  # 16->32
                self.conv_out = nn.Conv2d(base_ch, 3, 3, 1, 1)

            def forward(self, x_t: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
                # x_t: (B,3,H,W)
                h1 = torch.relu(self.conv1(x_t))
                h2 = torch.relu(self.conv2(h1))
                h2 = self.conv3(h2)

                temb = timestep_embedding(t, time_dim)  # (B, time_dim)
                temb = self.time_mlp(temb).unsqueeze(-1).unsqueeze(-1)  # (B, C, 1, 1)
                h2 = h2 + temb

                h = torch.relu(self.up(h2))
                out = self.conv_out(h)
                return out  # 预测噪声 ε

        model = SimpleNoisePredictor().to(device)
        lr = float(parameters.get("学习率", 1e-4))
        opt = optim.Adam(model.parameters(), lr=lr)

        # 训练步数上限：按样本量估算，但限制最大值，避免任务卡住。
        train_steps = max(20, min(120, n * 3))

        for _ in range(train_steps):
            idx = torch.randint(0, n, (batch_size,), device=device)
            x0 = images[idx]

            t = torch.randint(0, T, (batch_size,), device=device)
            noise = torch.randn_like(x0)

            a_bar = alphas_cumprod[t].view(-1, 1, 1, 1)
            sqrt_a_bar = torch.sqrt(a_bar)
            sqrt_one_minus = torch.sqrt(1.0 - a_bar)
            x_t = sqrt_a_bar * x0 + sqrt_one_minus * noise

            pred_noise = model(x_t, t)
            loss = torch.mean((pred_noise - noise) ** 2)

            opt.zero_grad()
            loss.backward()
            opt.step()

        return {
            "type": "diffusion",
            "model": model,
            "image_size": image_size,
            "device": device,
            "T": T,
            "betas": betas,
            "alphas": alphas,
            "alphas_cumprod": alphas_cumprod,
        }

    def generate_with_diffusion_from_context(
        self,
        diffusion_context: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """使用已训练好的 diffusion model 生成一张新图片。"""
        try:
            if not self._torch_available():
                return None
            model: nn.Module = diffusion_context["model"]
            T = int(diffusion_context["T"])
            device: torch.device = diffusion_context["device"]
            alphas = diffusion_context["alphas"]
            alphas_cumprod = diffusion_context["alphas_cumprod"]

            # 来自前端参数：扩散步数上限 / CFG引导阶数（本实现里CFG做简化缩放）
            cfg_scale = float(diffusion_context.get("cfg_scale", 1.0))
            inference_steps = int(diffusion_context.get("inference_steps", 50))

            # 进一步上限裁剪：避免推理过慢。
            inference_steps = max(1, min(inference_steps, 50, T))

            model.eval()
            with torch.no_grad():
                x = torch.randn(1, 3, int(diffusion_context["image_size"]), int(diffusion_context["image_size"]), device=device)

                # 把 inference_steps 映射到 [0, T-1] 的时间步序列
                # （uniform spacing 简化实现）
                for i in reversed(range(inference_steps)):
                    # 计算当前使用的 t
                    t = int(i * (T - 1) / max(1, inference_steps - 1))
                    t_tensor = torch.tensor([t], device=device, dtype=torch.long)

                    a_t = alphas[t].view(1, 1, 1, 1)
                    a_bar_t = alphas_cumprod[t].view(1, 1, 1, 1)
                    beta_t = 1.0 - a_t

                    pred_noise = model(x, t_tensor)
                    pred_noise = pred_noise * cfg_scale

                    # DDPM 公式（简化版）
                    coef = (1.0 - a_t) / torch.sqrt(1.0 - a_bar_t)
                    mean = (1.0 / torch.sqrt(a_t)) * (x - coef * pred_noise)
                    if t > 0:
                        sigma = torch.sqrt(beta_t)
                        x = mean + sigma * torch.randn_like(x)
                    else:
                        x = mean

            img_bgr = self._tensor_to_bgr_image(x[0])
            output_path = os.path.join(output_dir, f"diffusion_{index}.jpg")
            cv2.imwrite(output_path, img_bgr)
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
        """兼容旧接口：对单张图像做“弱化版 Diffusion 生成”。"""
        try:
            diffusion_context = self.train_diffusion([sample_path], parameters)
            if diffusion_context is None:
                img = cv2.imread(sample_path)
                if img is None:
                    return None
                # 退化为“多轮噪声扰动”（保证流程可跑）
                steps = int(parameters.get("扩散步数上限", 50))
                for _ in range(max(1, steps // 10)):
                    noise = np.random.normal(0, 0.1, img.shape)
                    img = img + noise
                    img = np.clip(img, 0, 255).astype(np.uint8)
                output_path = os.path.join(output_dir, f"diffusion_{index}.jpg")
                cv2.imwrite(output_path, img)
                return output_path

            # 把前端参数注入到采样上下文（train_diffusion 用固定的 T）
            diffusion_context["cfg_scale"] = float(parameters.get("CFG引导阶数", 1.0))
            diffusion_context["inference_steps"] = int(parameters.get("扩散步数上限", 50))
            return self.generate_with_diffusion_from_context(diffusion_context, output_dir, index)
        except Exception:
            return None

    # =========================
    # Transformer（深度学习生成增强）
    # =========================
    def train_vit_mae_generator(
        self,
        training_image_paths: List[str],
        parameters: Dict[str, Any],
        image_size: int = 32,
    ) -> Optional[Dict[str, Any]]:
        """训练一个轻量 ViT-MAE（Masked AutoEncoder）用于“遮挡patch -> 重建新样本”。

        设计目标：
        1) 仅依赖已有图像样本，无需额外标注；
        2) 通过“随机遮挡 + transformer重建”在生成时引入随机性，从而得到多样化增强样本；
        3) 为了让任务在 CPU 上可运行，将模型规模与训练步数做上限裁剪。

        前端参数（parameters）关键字（中文 key，必须与 get_algorithms / UI 配置一致）：
        - 掩码比例：mask_ratio（默认 0.75）
        - 学习率：lr（默认 1e-4）
        - 训练步数上限：train_steps_cap（默认 100）
        - patch大小：patch_size（默认 4；image_size 必须能被 patch_size 整除）
        """
        if not self._torch_available():
            return None
        device = torch.device("cpu")
        if len(training_image_paths) < 2:
            return None

        patch_size = int(parameters.get("patch大小", 4))
        if image_size % patch_size != 0:
            # 不满足 patch 整除条件时直接失败，交由上层回退方案。
            return None

        mask_ratio = float(parameters.get("掩码比例", 0.75))
        mask_ratio = max(0.0, min(mask_ratio, 0.95))

        lr = float(parameters.get("学习率", 1e-4))
        train_steps_cap = int(parameters.get("训练步数上限", 100))
        train_steps_cap = max(5, min(train_steps_cap, 300))

        # 读取并裁剪训练图片（上限由 max_images 控制，避免任务训练过慢）
        max_images = int(parameters.get("最大训练图片数", 32))
        max_images = max(2, min(max_images, 64))

        images = self._read_images_as_tensor(
            image_paths=training_image_paths,
            image_size=image_size,
            max_images=max_images,
            device=device,
        )
        if images is None or images.size(0) < 2:
            return None

        # (N,3,H,W) -> patchify
        # num_patches = (H/patch_size)^2
        num_patches_per_side = image_size // patch_size
        num_patches = num_patches_per_side * num_patches_per_side
        patch_dim = 3 * patch_size * patch_size

        def patchify(x: torch.Tensor) -> torch.Tensor:
            # x: (B,3,H,W)
            B, C, H, W = x.shape
            x = x.view(B, C, num_patches_per_side, patch_size, num_patches_per_side, patch_size)
            x = x.permute(0, 2, 4, 1, 3, 5).contiguous()  # (B, Nps, Nps, C, ps, ps)
            x = x.view(B, num_patches, patch_dim)  # (B, P, patch_dim)
            return x

        def unpatchify(patches: torch.Tensor) -> torch.Tensor:
            # patches: (B,P,patch_dim)
            B, P, D = patches.shape
            x = patches.view(B, num_patches_per_side, num_patches_per_side, 3, patch_size, patch_size)
            x = x.permute(0, 3, 1, 4, 2, 5).contiguous()  # (B,3,H, W)
            x = x.view(B, 3, image_size, image_size)
            return x

        # 一个很小的 ViT-MAE（重建器）
        embed_dim = int(parameters.get("模型维度", 128))
        num_heads = int(parameters.get("注意力头数", 4))
        num_layers = int(parameters.get("Transformer层数", 4))

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=embed_dim,
            nhead=max(1, num_heads),
            dim_feedforward=embed_dim * 4,
            dropout=0.0,
            activation="gelu",
            batch_first=True,
        )
        encoder = nn.TransformerEncoder(encoder_layer, num_layers=max(1, num_layers)).to(device)

        patch_embed = nn.Linear(patch_dim, embed_dim).to(device)
        mask_token = nn.Parameter(torch.zeros(1, 1, embed_dim, device=device))
        pos_embed = nn.Parameter(torch.zeros(1, num_patches, embed_dim, device=device))
        head = nn.Sequential(
            nn.LayerNorm(embed_dim),
            nn.Linear(embed_dim, patch_dim),
        ).to(device)

        # 简单初始化（避免训练一开始预测太偏）
        torch.nn.init.normal_(pos_embed, mean=0.0, std=0.02)
        torch.nn.init.normal_(mask_token, mean=0.0, std=0.02)

        opt = optim.Adam(list(patch_embed.parameters()) + list(encoder.parameters()) + list(head.parameters()) + [mask_token, pos_embed], lr=lr)

        n = images.size(0)
        batch_size = min(16, n)
        train_steps = min(train_steps_cap, max(20, n * 2))

        def forward(x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
            # mask: True 表示遮挡的 patch（B,P）
            patches = patchify(x)  # (B,P,D)
            tokens = patch_embed(patches)  # (B,P,E)

            # 将遮挡 token 替换为 mask_token
            mask_token_exp = mask_token.expand(tokens.size(0), tokens.size(1), -1)  # (B,P,E)
            tokens = torch.where(mask.unsqueeze(-1), mask_token_exp, tokens)

            tokens = tokens + pos_embed  # (B,P,E)
            h = encoder(tokens)  # (B,P,E)
            pred = head(h)  # (B,P,D)
            return pred, patches

        for _ in range(train_steps):
            idx = torch.randint(0, n, (batch_size,), device=device)
            x0 = images[idx]  # (B,3,H,W)
            # 随机生成 mask
            mask = torch.rand(batch_size, num_patches, device=device) < mask_ratio  # (B,P)
            # 确保至少有一些 patch 被遮挡，否则 loss 为空
            if mask.all():
                # 极端情况下重新采样一个更合理的 mask
                mask = torch.rand(batch_size, num_patches, device=device) < min(0.5, mask_ratio)

            pred, target = forward(x0, mask)
            loss = torch.mean((pred[mask] - target[mask]) ** 2)

            opt.zero_grad()
            loss.backward()
            opt.step()

        # 返回上下文用于采样
        model_ctx = {
            "type": "vit-mae",
            "image_size": image_size,
            "patch_size": patch_size,
            "mask_ratio": mask_ratio,
            "num_patches": num_patches,
            "patch_dim": patch_dim,
            "patchify": patchify,
            "unpatchify": unpatchify,
            "patch_embed": patch_embed,
            "mask_token": mask_token,
            "pos_embed": pos_embed,
            "encoder": encoder,
            "head": head,
            "device": device,
            # 生成时用真实样本作为“条件锚点”，提升重建结果的真实性
            "images": images,
        }
        return model_ctx

    def generate_with_transformer_from_context(
        self,
        transformer_ctx: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """使用训练后的 ViT-MAE 在“随机遮挡 mask”条件下重建出新样本。"""
        try:
            if not self._torch_available():
                return None
            patchify = transformer_ctx["patchify"]
            unpatchify = transformer_ctx["unpatchify"]
            patch_embed: nn.Linear = transformer_ctx["patch_embed"]
            mask_token: torch.nn.Parameter = transformer_ctx["mask_token"]
            pos_embed: torch.nn.Parameter = transformer_ctx["pos_embed"]
            encoder: nn.Module = transformer_ctx["encoder"]
            head: nn.Module = transformer_ctx["head"]
            device: torch.device = transformer_ctx["device"]

            mask_ratio = float(transformer_ctx["mask_ratio"])
            num_patches = int(transformer_ctx["num_patches"])
            patch_dim = int(transformer_ctx["patch_dim"])
            image_size = int(transformer_ctx["image_size"])
            images: torch.Tensor = transformer_ctx["images"]

            # 生成时取训练集中的一张真实图片作为条件锚点，再进行随机 mask + 重建，
            # 生成结果更接近“在真实样本上的多样化增强”。
            cond_idx = int(np.random.randint(0, images.size(0)))
            x0 = images[cond_idx : cond_idx + 1]  # (1,3,H,W) [-1,1]
            patches = patchify(x0)  # (1,P,D)

            mask = torch.rand(1, num_patches, device=device) < mask_ratio  # True=masked
            if mask.all():
                mask = torch.rand(1, num_patches, device=device) < min(0.5, mask_ratio)

            tokens = patch_embed(patches)  # (1,P,E)
            mask_token_exp = mask_token.expand(tokens.size(0), tokens.size(1), -1)  # (1,P,E)
            tokens = torch.where(mask.unsqueeze(-1), mask_token_exp, tokens)
            tokens = tokens + pos_embed

            h = encoder(tokens)
            pred = head(h)  # (1,P,D)

            # 重建：保留未遮挡 patch 的原始内容，只用预测 patch 填充遮挡区域。
            out_patches = torch.where(mask.unsqueeze(-1), pred, patches)
            x_rec = unpatchify(out_patches)  # (1,3,H,W)
            x_rec = x_rec.clamp(-1.0, 1.0)

            img_bgr = self._tensor_to_bgr_image(x_rec[0])
            output_path = os.path.join(output_dir, f"transformer_{index}.jpg")
            cv2.imwrite(output_path, img_bgr)
            return output_path
        except Exception:
            return None

    def generate_with_transformer(
        self,
        sample_path: str,
        parameters: Dict[str, Any],
        output_dir: str,
        index: int,
    ) -> Optional[str]:
        """兼容旧接口：对单张图像执行“弱版 Transformer 生成”。"""
        try:
            # 单张图片无法训练：退化为简单扰动以保证流程不阻塞
            img = cv2.imread(sample_path)
            if img is None:
                return None

            # 轻量“patch级扰动”近似：切分patch后随机抖动并重组
            patch_size = int(parameters.get("patch大小", 4))
            h, w = img.shape[:2]
            if h < patch_size or w < patch_size:
                out = cv2.GaussianBlur(img, (3, 3), 0)
                output_path = os.path.join(output_dir, f"transformer_{index}.jpg")
                cv2.imwrite(output_path, out)
                return output_path

            # 为简化，只对前景大致做 resize 再扰动
            img_r = cv2.resize(img, (32, 32), interpolation=cv2.INTER_AREA)
            ps = patch_size if 32 % patch_size == 0 else 4
            blocks = []
            for yy in range(0, 32, ps):
                row = []
                for xx in range(0, 32, ps):
                    row.append(img_r[yy:yy+ps, xx:xx+ps].copy())
                blocks.append(row)

            # 随机交换少量 patch，制造“Transformer式不确定性”的效果
            # （这不是严格的 ViT 重建，但保证单张生成不依赖训练）
            for _ in range(8):
                y1 = np.random.randint(0, len(blocks))
                x1 = np.random.randint(0, len(blocks[0]))
                y2 = np.random.randint(0, len(blocks))
                x2 = np.random.randint(0, len(blocks[0]))
                blocks[y1][x1], blocks[y2][x2] = blocks[y2][x2], blocks[y1][x1]

            out = np.zeros_like(img_r)
            for yy in range(0, 32, ps):
                for xx in range(0, 32, ps):
                    out[yy:yy+ps, xx:xx+ps] = blocks[yy//ps][xx//ps]

            out = cv2.GaussianBlur(out, (3, 3), 0)
            output_path = os.path.join(output_dir, f"transformer_{index}.jpg")
            cv2.imwrite(output_path, out)
            return output_path
        except Exception:
            return None
