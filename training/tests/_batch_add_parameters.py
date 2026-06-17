# -*- coding: utf-8 -*-
"""批量为所有插件添加 PARAMETERS 声明。

基于实际 run() 函数中 parameters.get() 调用生成，与 seed_data.py 保持一致的中文 label。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import re

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录

# ============================================================
# 插件 → 参数映射表
# ============================================================
# 格式: "相对路径": [list of param dicts]
# 每个 param dict 包含: name, type, label, default, min, max, options, description, required

PLUGIN_PARAMS: dict[str, list[dict[str, Any]]] = {
    # ==================== CLEANING PLUGINS ====================
    "plugins/cleaning/duplicate_detector.py": [],

    "plugins/cleaning/image_near_duplicate_detector.py": [
        {"name": "hamming_threshold", "type": "int", "label": "感知哈希距离阈值", "default": 6, "min": 1, "max": 64, "options": [], "description": "两个图像 dHash 的汉明距离不大于该值时视为近似重复", "required": False},
        {"name": "min_confidence", "type": "float", "label": "最低置信度", "default": 0.75, "min": 0.0, "max": 1.0, "options": [], "description": "输出建议的最低置信度下限", "required": False},
        {"name": "hash_size", "type": "int", "label": "哈希尺寸", "default": 8, "min": 4, "max": 16, "options": [], "description": "dHash 基础尺寸，默认生成 64 位指纹", "required": False},
    ],

    "plugins/cleaning/image_deblur.py": [
        {"name": "blur_threshold", "type": "int", "label": "模糊阈值", "default": 100, "min": 1, "max": 1000, "options": [], "description": "Laplacian方差低于此值时判定为模糊", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将去模糊后的图像写入磁盘", "required": False},
    ],

    "plugins/cleaning/image_denoise.py": [
        {"name": "noise_threshold", "type": "float", "label": "噪声阈值", "default": 12.0, "min": 0.0, "max": 255.0, "options": [], "description": "超过此噪声强度时触发去噪", "required": False},
        {"name": "denoise_strength", "type": "int", "label": "去噪强度", "default": 10, "min": 3, "max": 30, "options": [], "description": "fastNlMeansDenoisingColored的h参数，值越大去噪越强", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将去噪后的图像写入磁盘", "required": False},
    ],

    "plugins/cleaning/text_deduplicate.py": [
        {"name": "deduplicate_mode", "type": "select", "label": "去重模式", "default": "line", "min": None, "max": None, "options": ["line", "token"], "description": "line: 按行去重; token: 按词去重", "required": False},
        {"name": "apply", "type": "bool", "label": "写入清洗结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将去重后的文本写入磁盘", "required": False},
    ],

    "plugins/cleaning/text_stopwords.py": [
        {"name": "stop_words", "type": "string", "label": "额外停用词", "default": "", "min": None, "max": None, "options": [], "description": "用户自定义的额外停用词，逗号分隔", "required": False},
        {"name": "apply", "type": "bool", "label": "写入清洗结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将去停用词后的文本写入磁盘", "required": False},
    ],

    "plugins/cleaning/text_stemming.py": [
        {"name": "apply", "type": "bool", "label": "写入清洗结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将词干提取后的文本写入磁盘", "required": False},
    ],

    "plugins/cleaning/audio_denoise.py": [
        {"name": "snr_threshold", "type": "float", "label": "信噪比阈值(dB)", "default": 18.0, "min": 0.0, "max": 100.0, "options": [], "description": "低于此信噪比时触发去噪", "required": False},
        {"name": "noise_reduce_strength", "type": "float", "label": "降噪强度", "default": 1.0, "min": 0.1, "max": 3.0, "options": [], "description": "频谱门控的噪声削减倍数", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将去噪后的音频写入磁盘", "required": False},
    ],

    "plugins/cleaning/audio_normalize.py": [
        {"name": "target_peak", "type": "float", "label": "目标峰值幅度", "default": 0.95, "min": 0.1, "max": 1.0, "options": [], "description": "标准化后的音频峰值幅度", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将标准化后的音频写入磁盘", "required": False},
    ],

    "plugins/cleaning/audio_trim_silence.py": [
        {"name": "top_db", "type": "int", "label": "静音阈值(dB)", "default": 30, "min": 10, "max": 80, "options": [], "description": "低于此分贝值的片段视为静音", "required": False},
        {"name": "silence_ratio_threshold", "type": "float", "label": "静音比例阈值", "default": 0.2, "min": 0.0, "max": 1.0, "options": [], "description": "静音片段占比超过此值时触发修剪", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将修剪后的音频写入磁盘", "required": False},
    ],

    "plugins/cleaning/tabular_missing_values.py": [
        {"name": "missing_strategy", "type": "select", "label": "填充策略", "default": "mean", "min": None, "max": None, "options": ["mean", "median", "constant", "drop"], "description": "mean: 均值填充; median: 中位数填充; constant: 常数填充; drop: 删除含空行", "required": False},
        {"name": "fill_value", "type": "float", "label": "填充常数值", "default": 0.0, "min": None, "max": None, "options": [], "description": "当策略为constant时使用的填充值", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将填充后的表格写入磁盘", "required": False},
    ],

    "plugins/cleaning/tabular_outliers.py": [
        {"name": "outlier_method", "type": "select", "label": "检测方法", "default": "iqr", "min": None, "max": None, "options": ["iqr", "zscore"], "description": "iqr: 四分位距法; zscore: z分数法", "required": False},
        {"name": "zscore_threshold", "type": "float", "label": "z分数阈值", "default": 3.0, "min": 1.0, "max": 10.0, "options": [], "description": "z分数超过此阈值视为异常值", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将处理后的表格写入磁盘", "required": False},
    ],

    "plugins/cleaning/tabular_normalize.py": [
        {"name": "normalization", "type": "select", "label": "归一化方法", "default": "minmax", "min": None, "max": None, "options": ["minmax", "zscore"], "description": "minmax: 最小-最大归一化; zscore: z分数标准化", "required": False},
        {"name": "apply", "type": "bool", "label": "写入修复结果", "default": True, "min": None, "max": None, "options": [], "description": "是否将归一化后的表格写入磁盘", "required": False},
    ],

    # ==================== GENERATION PLUGINS (IMAGE) ====================
    "plugins/generation/copy_augmenter.py": [],

    "plugins/generation/geometric_image_augmenter.py": [
        {"name": "rotation_degrees", "type": "float", "label": "旋转角度", "default": 0.0, "min": -360.0, "max": 360.0, "options": [], "description": "围绕图像中心旋转的角度", "required": False},
        {"name": "scale", "type": "float", "label": "缩放比例", "default": 1.0, "min": 0.1, "max": 5.0, "options": [], "description": "几何变换缩放比例", "required": False},
        {"name": "translate_x_pct", "type": "float", "label": "水平平移百分比", "default": 0.0, "min": -100.0, "max": 100.0, "options": [], "description": "相对图像宽度的水平平移百分比", "required": False},
        {"name": "translate_y_pct", "type": "float", "label": "垂直平移百分比", "default": 0.0, "min": -100.0, "max": 100.0, "options": [], "description": "相对图像高度的垂直平移百分比", "required": False},
        {"name": "flip_horizontal", "type": "bool", "label": "水平翻转", "default": False, "min": None, "max": None, "options": [], "description": "是否执行水平翻转", "required": False},
        {"name": "flip_vertical", "type": "bool", "label": "垂直翻转", "default": False, "min": None, "max": None, "options": [], "description": "是否执行垂直翻转", "required": False},
        {"name": "border_value", "type": "int", "label": "边界填充值", "default": 0, "min": 0, "max": 255, "options": [], "description": "仿射变换边界填充像素值", "required": False},
    ],

    "plugins/generation/style_transfer_image_augmenter.py": [
        {"name": "strength", "type": "float", "label": "风格强度", "default": 0.7, "min": 0.0, "max": 1.0, "options": [], "description": "风格化叠加强度，0为原图，1为纯边缘", "required": False},
    ],

    "plugins/generation/color_space_image_augmenter.py": [
        {"name": "brightness", "type": "float", "label": "亮度增量", "default": 0.0, "min": -1.0, "max": 1.0, "options": [], "description": "亮度调整增量", "required": False},
        {"name": "contrast", "type": "float", "label": "对比度系数", "default": 1.0, "min": 0.0, "max": 3.0, "options": [], "description": "对比度缩放系数", "required": False},
        {"name": "saturation", "type": "float", "label": "饱和度系数", "default": 1.0, "min": 0.0, "max": 3.0, "options": [], "description": "饱和度缩放系数", "required": False},
        {"name": "hue", "type": "float", "label": "色相偏移", "default": 0.0, "min": -180.0, "max": 180.0, "options": [], "description": "色相偏移量", "required": False},
        {"name": "pca_jitter", "type": "float", "label": "PCA颜色抖动", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "PCA颜色抖动强度", "required": False},
    ],

    "plugins/generation/clarity_image_augmenter.py": [
        {"name": "blur_strength", "type": "float", "label": "模糊强度", "default": 0.0, "min": 0.0, "max": 10.0, "options": [], "description": "高斯模糊sigma值", "required": False},
        {"name": "blur_kernel", "type": "int", "label": "模糊核大小", "default": 5, "min": 3, "max": 31, "options": [], "description": "高斯模糊卷积核尺寸（奇数）", "required": False},
        {"name": "sharpen_strength", "type": "float", "label": "锐化强度", "default": 0.0, "min": 0.0, "max": 5.0, "options": [], "description": "反锐化掩模锐化强度", "required": False},
        {"name": "sharpen_amount", "type": "float", "label": "锐化叠加比例", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "锐化叠加比例", "required": False},
    ],

    "plugins/generation/occlusion_image_augmenter.py": [
        {"name": "occlusion_type", "type": "select", "label": "遮挡类型", "default": "random_erase", "min": None, "max": None, "options": ["random_erase", "cutout", "gridmask"], "description": "遮挡增强方式", "required": False},
        {"name": "erase_count", "type": "int", "label": "擦除次数", "default": 1, "min": 1, "max": 20, "options": [], "description": "随机擦除的矩形数量", "required": False},
        {"name": "area_ratio", "type": "float", "label": "面积比例", "default": 0.2, "min": 0.01, "max": 0.5, "options": [], "description": "擦除区域占图像面积的比例上限", "required": False},
    ],

    "plugins/generation/environment_simulation_image_augmenter.py": [
        {"name": "fog_intensity", "type": "float", "label": "雾气浓度", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "大气散射模拟强度", "required": False},
        {"name": "snow_intensity", "type": "float", "label": "雪花强度", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "雪花叠加强度", "required": False},
        {"name": "shadow_intensity", "type": "float", "label": "阴影强度", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "随机阴影块强度", "required": False},
    ],

    "plugins/generation/deformation_distortion_image_augmenter.py": [
        {"name": "elastic_strength", "type": "float", "label": "弹性形变强度", "default": 0.0, "min": 0.0, "max": 50.0, "options": [], "description": "弹性形变位移强度", "required": False},
        {"name": "elastic_gaussian_kernel", "type": "float", "label": "弹性高斯核", "default": 10.0, "min": 1.0, "max": 50.0, "options": [], "description": "弹性形变高斯平滑核大小", "required": False},
        {"name": "distortion_k1", "type": "float", "label": "径向畸变k1", "default": 0.0, "min": -1.0, "max": 1.0, "options": [], "description": "径向畸变一阶系数", "required": False},
        {"name": "distortion_k2", "type": "float", "label": "径向畸变k2", "default": 0.0, "min": -1.0, "max": 1.0, "options": [], "description": "径向畸变二阶系数", "required": False},
    ],

    "plugins/generation/imaging_simulation_image_augmenter.py": [
        {"name": "shot_noise", "type": "float", "label": "散粒噪声强度", "default": 0.0, "min": 0.0, "max": 0.5, "options": [], "description": "泊松分布散粒噪声强度", "required": False},
        {"name": "read_noise", "type": "float", "label": "读出噪声标准差", "default": 0.0, "min": 0.0, "max": 0.1, "options": [], "description": "高斯分布读出噪声标准差", "required": False},
        {"name": "blur_kernel", "type": "int", "label": "模糊核大小", "default": 0, "min": 0, "max": 15, "options": [], "description": "传感器模糊核大小，0表示不模糊", "required": False},
        {"name": "downsample", "type": "float", "label": "下采样比例", "default": 1.0, "min": 0.1, "max": 1.0, "options": [], "description": "下采样比例，1.0表示不变", "required": False},
    ],

    "plugins/generation/channel_shuffle_image_augmenter.py": [
        {"name": "shuffle", "type": "bool", "label": "通道混洗", "default": True, "min": None, "max": None, "options": [], "description": "是否随机混洗颜色通道顺序", "required": False},
    ],

    "plugins/generation/cross_modal_fusion_image_augmenter.py": [
        {"name": "clahe_clip", "type": "float", "label": "CLAHE剪切限制", "default": 2.0, "min": 0.0, "max": 10.0, "options": [], "description": "限制对比度自适应直方图均衡化的剪切阈值", "required": False},
        {"name": "ir_weight", "type": "float", "label": "红外权重", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "伪红外通道融合权重", "required": False},
    ],

    "plugins/generation/wgan_gp_image_augmenter.py": [
        {"name": "gradient_penalty", "type": "float", "label": "梯度惩罚系数", "default": 10.0, "min": 0.1, "max": 50.0, "options": [], "description": "WGAN-GP梯度惩罚权重", "required": False},
        {"name": "discriminator_iterations", "type": "int", "label": "判别器迭代次数", "default": 5, "min": 1, "max": 20, "options": [], "description": "每次生成器更新的判别器训练步数", "required": False},
        {"name": "learning_rate", "type": "float", "label": "学习率", "default": 0.0001, "min": 1e-6, "max": 0.1, "options": [], "description": "优化器学习率", "required": False},
    ],

    "plugins/generation/diffusion_image_augmenter.py": [
        {"name": "diffusion_steps", "type": "int", "label": "扩散步数", "default": 1000, "min": 10, "max": 5000, "options": [], "description": "扩散过程的最大时间步数", "required": False},
        {"name": "cfg_guidance_scale", "type": "float", "label": "CFG引导强度", "default": 7.5, "min": 0.0, "max": 20.0, "options": [], "description": "无分类器引导的引导强度", "required": False},
    ],

    "plugins/generation/vit_mae_image_augmenter.py": [
        {"name": "mask_ratio", "type": "float", "label": "掩码比例", "default": 0.75, "min": 0.1, "max": 0.95, "options": [], "description": "图像patch掩码比例", "required": False},
        {"name": "learning_rate", "type": "float", "label": "学习率", "default": 0.0001, "min": 1e-6, "max": 0.1, "options": [], "description": "训练学习率", "required": False},
        {"name": "training_steps", "type": "int", "label": "训练步数", "default": 100, "min": 10, "max": 10000, "options": [], "description": "模拟训练迭代步数", "required": False},
        {"name": "patch_size", "type": "int", "label": "Patch大小", "default": 4, "min": 2, "max": 32, "options": [], "description": "ViT patch划分尺寸", "required": False},
    ],

    # ==================== GENERATION PLUGINS (AUDIO) ====================
    "plugins/generation/noise_injection_audio_augmenter.py": [
        {"name": "noise_type", "type": "select", "label": "噪声类型", "default": "white", "min": None, "max": None, "options": ["white", "pink"], "description": "white: 白噪声; pink: 粉红噪声", "required": False},
        {"name": "noise_intensity", "type": "float", "label": "噪声强度", "default": 0.1, "min": 0.0, "max": 1.0, "options": [], "description": "噪声幅度峰值", "required": False},
    ],

    "plugins/generation/spectrum_reconstruction_audio_augmenter.py": [
        {"name": "freq_range", "type": "string", "label": "频谱范围(Hz)", "default": "[0, 4000]", "min": None, "max": None, "options": [], "description": "频谱重构的起始和截止频率，格式 [low, high]", "required": False},
    ],

    "plugins/generation/tempo_pitch_audio_augmenter.py": [
        {"name": "rate", "type": "float", "label": "时间拉伸速率", "default": 1.0, "min": 0.5, "max": 2.0, "options": [], "description": "语速拉伸系数，>1变快，<1变慢", "required": False},
        {"name": "n_steps", "type": "float", "label": "音高半音偏移", "default": 0.0, "min": -12.0, "max": 12.0, "options": [], "description": "半音偏移量，正值为升调", "required": False},
    ],

    "plugins/generation/energy_amplitude_audio_augmenter.py": [
        {"name": "volume_scale", "type": "float", "label": "音量缩放", "default": 1.0, "min": 0.0, "max": 5.0, "options": [], "description": "线性音量缩放系数", "required": False},
        {"name": "mute_probability", "type": "float", "label": "静音触发概率", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "每个静音段的触发概率", "required": False},
        {"name": "mute_count", "type": "int", "label": "静音段数量", "default": 1, "min": 0, "max": 10, "options": [], "description": "随机插入的静音段数量", "required": False},
        {"name": "min_sec", "type": "float", "label": "最短静音(秒)", "default": 0.05, "min": 0.01, "max": 1.0, "options": [], "description": "单个静音段最短时长", "required": False},
        {"name": "max_sec", "type": "float", "label": "最长静音(秒)", "default": 0.2, "min": 0.05, "max": 2.0, "options": [], "description": "单个静音段最长时长", "required": False},
    ],

    "plugins/generation/timeseries_structure_audio_augmenter.py": [
        {"name": "operation", "type": "select", "label": "操作类型", "default": "mix", "min": None, "max": None, "options": ["mix", "shift", "crop", "concat", "reverse"], "description": "时序变换操作类型", "required": False},
        {"name": "shift_sec", "type": "float", "label": "偏移量(秒)", "default": 0.2, "min": 0.01, "max": 5.0, "options": [], "description": "时间偏移量", "required": False},
        {"name": "crop_ratio", "type": "float", "label": "裁剪保留比例", "default": 0.9, "min": 0.1, "max": 0.99, "options": [], "description": "随机裁剪保留比例", "required": False},
        {"name": "concat_segments", "type": "int", "label": "拼接段数", "default": 2, "min": 2, "max": 10, "options": [], "description": "随机拼接的音频段数量", "required": False},
        {"name": "reverse_probability", "type": "float", "label": "反转概率", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "音频反转的触发概率", "required": False},
    ],

    "plugins/generation/channel_config_audio_augmenter.py": [
        {"name": "target_channel", "type": "select", "label": "目标声道", "default": "auto", "min": None, "max": None, "options": ["auto", "mono", "stereo"], "description": "目标声道配置", "required": False},
        {"name": "mix_strategy", "type": "select", "label": "混合策略", "default": "avg", "min": None, "max": None, "options": ["avg", "max", "min"], "description": "多声道混合策略", "required": False},
        {"name": "dither", "type": "float", "label": "抖动幅度", "default": 0.002, "min": 0.0, "max": 0.1, "options": [], "description": "声道抖动噪声幅度", "required": False},
        {"name": "swap_probability", "type": "float", "label": "声道交换概率", "default": 0.2, "min": 0.0, "max": 1.0, "options": [], "description": "左右声道交换概率", "required": False},
    ],

    "plugins/generation/specaugment_audio_augmenter.py": [
        {"name": "mel_bins", "type": "int", "label": "Mel频带数", "default": 64, "min": 16, "max": 256, "options": [], "description": "Mel频谱频带数量", "required": False},
        {"name": "n_fft", "type": "int", "label": "FFT点数", "default": 1024, "min": 256, "max": 4096, "options": [], "description": "STFT的FFT窗口大小", "required": False},
        {"name": "hop", "type": "int", "label": "帧移", "default": 256, "min": 64, "max": 1024, "options": [], "description": "STFT帧移", "required": False},
        {"name": "freq_mask_param", "type": "int", "label": "频率掩码宽度", "default": 8, "min": 1, "max": 32, "options": [], "description": "频率维度掩码的最大宽度", "required": False},
        {"name": "time_mask_param", "type": "int", "label": "时间掩码宽度", "default": 8, "min": 1, "max": 32, "options": [], "description": "时间维度掩码的最大宽度", "required": False},
        {"name": "inversion_iterations", "type": "int", "label": "反演迭代次数", "default": 16, "min": 1, "max": 100, "options": [], "description": "Griffin-Lim迭代次数", "required": False},
    ],

    "plugins/generation/filter_processing_audio_augmenter.py": [
        {"name": "filter_type", "type": "select", "label": "滤波类型", "default": "bandpass", "min": None, "max": None, "options": ["bandpass", "lowpass", "highpass", "bandstop"], "description": "滤波器类型", "required": False},
        {"name": "low_cutoff_hz", "type": "float", "label": "低截止频率(Hz)", "default": 300.0, "min": 20.0, "max": 20000.0, "options": [], "description": "低端截止频率", "required": False},
        {"name": "high_cutoff_hz", "type": "float", "label": "高截止频率(Hz)", "default": 3000.0, "min": 20.0, "max": 20000.0, "options": [], "description": "高端截止频率", "required": False},
    ],

    "plugins/generation/environment_noise_injection_audio_augmenter.py": [
        {"name": "noise_type", "type": "select", "label": "噪声类型", "default": "white", "min": None, "max": None, "options": ["white", "pink", "brown", "uniform"], "description": "环境噪声频谱类型", "required": False},
        {"name": "target_snr", "type": "float", "label": "目标SNR(dB)", "default": 10.0, "min": -20.0, "max": 40.0, "options": [], "description": "目标信噪比", "required": False},
    ],

    "plugins/generation/spatial_acoustics_audio_augmenter.py": [
        {"name": "effect_type", "type": "select", "label": "效果类型", "default": "echo", "min": None, "max": None, "options": ["echo", "reverb", "both"], "description": "空间声学效果类型", "required": False},
        {"name": "probability", "type": "float", "label": "触发概率", "default": 0.8, "min": 0.0, "max": 1.0, "options": [], "description": "效果作用概率", "required": False},
        {"name": "count", "type": "int", "label": "回声次数", "default": 3, "min": 1, "max": 10, "options": [], "description": "回声重复次数", "required": False},
        {"name": "delay", "type": "float", "label": "延迟(秒)", "default": 0.3, "min": 0.05, "max": 2.0, "options": [], "description": "回声/混响延迟时间", "required": False},
        {"name": "decay", "type": "float", "label": "衰减系数", "default": 0.6, "min": 0.0, "max": 1.0, "options": [], "description": "回声/混响衰减系数", "required": False},
        {"name": "tau", "type": "float", "label": "混响时间常数", "default": 0.5, "min": 0.1, "max": 5.0, "options": [], "description": "指数衰减混响的时间常数", "required": False},
    ],

    "plugins/generation/quality_distortion_audio_augmenter.py": [
        {"name": "downsample_ratio", "type": "float", "label": "降采样比例", "default": 0.8, "min": 0.1, "max": 1.0, "options": [], "description": "降采样/升采样比例", "required": False},
        {"name": "quantize_bits", "type": "int", "label": "量化位深", "default": 8, "min": 2, "max": 32, "options": [], "description": "量化比特深度", "required": False},
        {"name": "distortion_drive", "type": "float", "label": "失真驱动量", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "tanh饱和失真驱动量", "required": False},
    ],

    "plugins/generation/composite_audio_augmenter.py": [
        {"name": "combination_count", "type": "int", "label": "组合次数", "default": 3, "min": 1, "max": 10, "options": [], "description": "每次随机选取并应用的增强策略数量", "required": False},
        {"name": "include_specaugment", "type": "bool", "label": "包含SpecAugment", "default": True, "min": None, "max": None, "options": [], "description": "是否将SpecAugment纳入候选策略池", "required": False},
        {"name": "include_spatial", "type": "bool", "label": "包含空间声学", "default": True, "min": None, "max": None, "options": [], "description": "是否将空间声学纳入候选策略池", "required": False},
    ],

    # ==================== GENERATION PLUGINS (TEXT) ====================
    "plugins/generation/synonym_replacement_text_augmenter.py": [
        {"name": "replacement_ratio", "type": "float", "label": "替换比例", "default": 0.3, "min": 0.0, "max": 1.0, "options": [], "description": "文本中词语被同义词替换的比例", "required": False},
    ],

    "plugins/generation/back_translation_text_augmenter.py": [
        {"name": "intermediate_language", "type": "select", "label": "中间语言", "default": "en", "min": None, "max": None, "options": ["en", "ja", "ko"], "description": "回译的中间语言代码", "required": False},
        {"name": "back_translate_probability", "type": "float", "label": "回译概率", "default": 1.0, "min": 0.0, "max": 1.0, "options": [], "description": "对每个样本执行回译的概率", "required": False},
        {"name": "sentence_restructure_strength", "type": "float", "label": "句式重构强度", "default": 0.3, "min": 0.0, "max": 1.0, "options": [], "description": "回译后的句式重组强度", "required": False},
    ],

    "plugins/generation/vocabulary_phrase_text_augmenter.py": [
        {"name": "replacement_ratio", "type": "float", "label": "替换比例", "default": 0.3, "min": 0.0, "max": 1.0, "options": [], "description": "词汇/短语被替换的比例", "required": False},
        {"name": "pos_constraint", "type": "string", "label": "词性约束", "default": "", "min": None, "max": None, "options": [], "description": "限定替换的词性，留空表示无约束", "required": False},
        {"name": "phrase_level", "type": "bool", "label": "短语级替换", "default": True, "min": None, "max": None, "options": [], "description": "是否进行短语级别替换", "required": False},
    ],

    "plugins/generation/structure_noise_text_augmenter.py": [
        {"name": "perturbation_strength", "type": "float", "label": "扰动强度", "default": 0.1, "min": 0.0, "max": 1.0, "options": [], "description": "字符级噪声扰动强度", "required": False},
    ],

    "plugins/generation/context_embedding_text_augmenter.py": [
        {"name": "mask_ratio", "type": "float", "label": "Mask比例", "default": 0.1, "min": 0.0, "max": 1.0, "options": [], "description": "被替换的词语比例", "required": False},
        {"name": "cross_lingual_strength", "type": "float", "label": "跨语言增强强度", "default": 0.0, "min": 0.0, "max": 1.0, "options": [], "description": "跨语言增强强度", "required": False},
    ],

    "plugins/generation/style_controlled_text_augmenter.py": [
        {"name": "style_label", "type": "select", "label": "目标风格", "default": "formal", "min": None, "max": None, "options": ["formal", "casual", "concise"], "description": "formal: 正式; casual: 口语化; concise: 简洁", "required": False},
        {"name": "conciseness_strength", "type": "float", "label": "简洁压缩强度", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "简洁风格下的压缩强度", "required": False},
    ],

    "plugins/generation/sentence_reordering_text_augmenter.py": [
        {"name": "reorder_granularity", "type": "select", "label": "重排粒度", "default": "sentence", "min": None, "max": None, "options": ["sentence", "paragraph"], "description": "sentence: 句子级; paragraph: 段落级", "required": False},
        {"name": "shuffle_strength", "type": "float", "label": "打乱强度", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "打乱的比例强度", "required": False},
        {"name": "preserve_first_last", "type": "bool", "label": "保留首尾", "default": True, "min": None, "max": None, "options": [], "description": "是否保留首句/首段和尾句/尾段不变", "required": False},
    ],

    # ==================== TRAINING PLUGINS ====================
    "plugins/training/demo_classifier.py": [
        {"name": "epochs", "type": "int", "label": "训练轮次", "default": 3, "min": 1, "max": 1000, "options": [], "description": "模拟训练的epoch数量", "required": False},
    ],

    "plugins/training/ship_classifier.py": [],

    "plugins/training/sonar_oltr_classifier.py": [
        {"name": "backbone", "type": "string", "label": "骨干网络", "default": "resnet18", "min": None, "max": None, "options": [], "description": "预训练骨干网络名称", "required": False},
        {"name": "batch_size", "type": "int", "label": "批大小", "default": 32, "min": 1, "max": 512, "options": [], "description": "训练批次大小", "required": False},
        {"name": "epochs", "type": "int", "label": "训练轮次", "default": 10, "min": 1, "max": 500, "options": [], "description": "训练epoch数量", "required": False},
        {"name": "learning_rate", "type": "float", "label": "学习率", "default": 0.01, "min": 1e-6, "max": 1.0, "options": [], "description": "初始学习率（SGD优化器）", "required": False},
        {"name": "train_ratio", "type": "float", "label": "训练集比例", "default": 0.6, "min": 0.1, "max": 0.9, "options": [], "description": "数据集划分中训练集占比", "required": False},
        {"name": "val_ratio", "type": "float", "label": "验证集比例", "default": 0.2, "min": 0.05, "max": 0.5, "options": [], "description": "数据集划分中验证集占比", "required": False},
    ],

    # ==================== EVALUATION PLUGINS ====================
    "plugins/evaluation/sample_count_comparator.py": [],

    "plugins/evaluation/multi_agent_simulation.py": [
        {"name": "agent_count", "type": "int", "label": "智能体数量", "default": 4, "min": 1, "max": 100, "options": [], "description": "参与仿真评估的智能体数量", "required": False},
    ],

    "plugins/evaluation/sonar_oltr_plud.py": [
        {"name": "model_checkpoint_path", "type": "string", "label": "模型检查点路径", "default": "", "min": None, "max": None, "options": [], "description": "训练好的模型检查点文件路径（必填）", "required": True},
        {"name": "backbone", "type": "string", "label": "骨干网络", "default": "resnet18", "min": None, "max": None, "options": [], "description": "预训练骨干网络名称", "required": False},
        {"name": "batch_size", "type": "int", "label": "批大小", "default": 32, "min": 1, "max": 512, "options": [], "description": "批次大小", "required": False},
        {"name": "train_class_num", "type": "int", "label": "已知类数量", "default": 5, "min": 1, "max": 100, "options": [], "description": "开放集识别中的已知类别数", "required": False},
        {"name": "weibull_tail", "type": "int", "label": "Weibull尾部大小", "default": 20, "min": 1, "max": 1000, "options": [], "description": "拟合Weibull分布时使用的尾部样本数", "required": False},
        {"name": "weibull_alpha", "type": "int", "label": "OpenMax alpha", "default": 2, "min": 1, "max": 10, "options": [], "description": "OpenMax重校准的top-k alpha参数", "required": False},
        {"name": "weibull_threshold", "type": "float", "label": "未知类概率阈值", "default": 0.5, "min": 0.0, "max": 1.0, "options": [], "description": "判定为未知类的概率阈值", "required": False},
    ],
}


# ============================================================
# 核心逻辑
# ============================================================

def indent(text: str, spaces: int = 0) -> str:
    """将多行文本添加指定缩进。"""
    prefix = " " * spaces
    return "\n".join(prefix + line if line else line for line in text.split("\n"))


def format_parameters(params: list[dict[str, Any]]) -> str:
    """将参数列表格式化为 Python 代码字符串（无类型注解，无需额外 import）。"""
    if not params:
        return "PARAMETERS = []\n\n"

    lines = ["PARAMETERS = ["]
    for i, p in enumerate(params):
        lines.append("    {")
        lines.append(f'        "name": {p["name"]!r},')
        lines.append(f'        "type": {p["type"]!r},')
        lines.append(f'        "label": {p["label"]!r},')
        default = p["default"]
        lines.append(f"        \"default\": {default!r},")
        for key in ["min", "max"]:
            val = p.get(key)
            lines.append(f"        \"{key}\": {val!r},")
        lines.append(f'        "options": {p["options"]!r},')
        lines.append(f'        "description": {p["description"]!r},')
        lines.append(f"        \"required\": {p['required']!r},")
        lines.append("    }," if i < len(params) - 1 else "    },")
    lines.append("]")
    lines.append("")
    return "\n".join(lines) + "\n"


def insert_parameters(file_path: Path, params_block: str) -> bool:
    """在 def run( 之前插入 PARAMETERS 声明。"""
    content = file_path.read_text(encoding="utf-8")

    # 如果已有 PARAMETERS，跳过
    if re.search(r'^PARAMETERS\s*[:=]', content, re.MULTILINE):
        return False

    # 找到 def run( 的位置
    match = re.search(r'^(def run\(payload)', content, re.MULTILINE)
    if not match:
        print(f"  WARNING: def run( not found in {file_path}")
        return False

    insert_pos = match.start()
    # 在 def run 之前的空行处插入
    before = content[:insert_pos]
    after = content[insert_pos:]

    # 确保 def run 前有一个空行
    if not before.endswith("\n\n"):
        if before.endswith("\n"):
            before = before + "\n"
        else:
            before = before + "\n\n"

    new_content = before + params_block + "\n" + after
    file_path.write_text(new_content, encoding="utf-8")
    return True


def main():
    root = ROOT
    updated = 0
    skipped = 0
    errors = []

    for rel_path, params in sorted(PLUGIN_PARAMS.items()):
        file_path = root / rel_path
        if not file_path.exists():
            errors.append(f"MISSING: {rel_path}")
            continue

        params_block = format_parameters(params)
        try:
            if insert_parameters(file_path, params_block):
                print(f"  OK: {rel_path} ({len(params)} params)")
                updated += 1
            else:
                print(f"  SKIP: {rel_path} (already has PARAMETERS)")
                skipped += 1
        except Exception as exc:
            errors.append(f"ERROR: {rel_path}: {exc}")

    print(f"\n{'='*60}")
    print(f"Updated: {updated}, Skipped: {skipped}, Errors: {len(errors)}")
    if errors:
        for e in errors:
            print(f"  {e}")


if __name__ == "__main__":
    main()
