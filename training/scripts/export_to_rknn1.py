#!/usr/bin/env python3
"""
RKNN-Toolkit1 模型导出脚本

功能: 将训练好的 PyTorch 模型导出为 RK3399Pro 可用的 .rknn 格式
流程: PyTorch (.pt) → ONNX (.onnx) → RKNN (.rknn)

依赖:
    pip install rknn-toolkit  (RKNN-Toolkit1, 仅支持 Python 3.6/3.7)
    pip install onnx torch

用法:
    # 导出 YOLOv5n
    python export_to_rknn1.py --input yolov5n.pt --output yolov5n.rknn --type yolov5

    # 导出 OSNet (ReID)
    python export_to_rknn1.py --input osnet.pt --output osnet.rknn --type osnet

    # INT8 量化导出 (需要校准数据集)
    python export_to_rknn1.py --input yolov5n.pt --output yolov5n_int8.rknn --type yolov5 --quantize --calib-dir ./calib_images

    # 查看模型信息
    python export_to_rknn1.py --input model.rknn --info
"""
import argparse
import os
import sys
import numpy as np

# RKNN-Toolkit1 导入
try:
    from rknn.api import RKNN
except ImportError:
    print("Error: rknn-toolkit not installed. Install with:")
    print("  pip install rknn-toolkit")
    sys.exit(1)


# ── ONNX 导出 ─────────────────────────────────────────────
def export_onnx_yolov5(pt_path: str, onnx_path: str,
                       img_size: int = 640) -> None:
    """将 YOLOv5 PyTorch 模型导出为 ONNX"""
    import torch

    print(f"[ONNX] Loading PyTorch model: {pt_path}")
    model = torch.load(pt_path, map_location='cpu', weights_only=False)
    model = model['model'] if isinstance(model, dict) and 'model' in model else model
    model.eval()

    dummy_input = torch.randn(1, 3, img_size, img_size)

    print(f"[ONNX] Exporting to: {onnx_path}")
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        opset_version=12,
        input_names=['images'],
        output_names=['output0', 'output1', 'output2'],
        dynamic_axes={'images': {0: 'batch'},
                      'output0': {0: 'batch'},
                      'output1': {0: 'batch'},
                      'output2': {0: 'batch'}}
    )
    print("[ONNX] Export complete")


def export_onnx_osnet(pt_path: str, onnx_path: str) -> None:
    """将 OSNet ReID 模型导出为 ONNX"""
    import torch

    print(f"[ONNX] Loading OSNet model: {pt_path}")
    model = torch.load(pt_path, map_location='cpu', weights_only=False)
    model.eval()

    # OSNet 输入: 1×3×256×128 (H×W)
    dummy_input = torch.randn(1, 3, 256, 128)

    print(f"[ONNX] Exporting to: {onnx_path}")
    torch.onnx.export(
        model,
        dummy_input,
        onnx_path,
        opset_version=12,
        input_names=['input'],
        output_names=['feature']
    )
    print("[ONNX] Export complete")


# ── RKNN 导出 ─────────────────────────────────────────────
def export_rknn(onnx_path: str, rknn_path: str,
                quantize: bool = False,
                calib_dir: str = None,
                target_platform: str = "rk3399pro") -> None:
    """将 ONNX 模型转换为 RKNN 格式"""

    rknn = RKNN()

    # 配置
    print(f"[RKNN] Configuring for platform: {target_platform}")
    rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        reorder_channel='0 1 2',
        target_platform=target_platform,
        optimization_level=3
    )

    # 加载 ONNX
    print(f"[RKNN] Loading ONNX: {onnx_path}")
    ret = rknn.load_onnx(model=onnx_path)
    if ret != 0:
        print(f"[RKNN] Failed to load ONNX: {ret}")
        sys.exit(1)

    # 构建模型
    print("[RKNN] Building model...")
    do_quantization = quantize
    ret = rknn.build(do_quantization=do_quantization)
    if ret != 0:
        print(f"[RKNN] Build failed: {ret}")
        sys.exit(1)

    # INT8 量化校准
    if quantize and calib_dir:
        import cv2
        print(f"[RKNN] Running INT8 calibration with: {calib_dir}")
        calib_images = []
        for fname in sorted(os.listdir(calib_dir))[:200]:
            if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                calib_images.append(os.path.join(calib_dir, fname))

        if calib_images:
            # 加载校准图像并执行推理以收集量化统计信息
            for idx, img_path in enumerate(calib_images[:100]):
                img = cv2.imread(img_path)
                if img is None:
                    continue
                # 按模型输入尺寸预处理 (LetterBox)
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img = cv2.resize(img, (640, 640))
                img = img.astype(np.float32) / 255.0
                img = np.expand_dims(img, axis=0)
                # 执行推理以收集量化统计
                rknn.inference(inputs=[img])
                if (idx + 1) % 20 == 0:
                    print(f"  Calibration progress: {idx + 1}/{len(calib_images[:100])}")
            print(f"[RKNN] Calibration done with {len(calib_images[:100])} images")
        else:
            print("[RKNN] WARNING: No calibration images found, INT8 accuracy may be poor")

    # 导出
    print(f"[RKNN] Exporting to: {rknn_path}")
    ret = rknn.export_rknn(rknn_path)
    if ret != 0:
        print(f"[RKNN] Export failed: {ret}")
        sys.exit(1)

    print(f"[RKNN] Model exported: {rknn_path}")
    rknn.release()


def show_model_info(rknn_path: str) -> None:
    """查看 RKNN 模型信息"""
    rknn = RKNN()
    ret = rknn.load_rknn(rknn_path)
    if ret != 0:
        print(f"Failed to load RKNN model: {ret}")
        sys.exit(1)

    # 查询模型信息
    print(f"\n=== Model: {rknn_path} ===")
    print(f"SDK Version: {rknn.get_sdk_version()}")

    # 输入输出信息
    inputs = rknn.query(0)  # RKNN_QUERY_INPUT_ATTR
    outputs = rknn.query(1)  # RKNN_QUERY_OUTPUT_ATTR

    print(f"\nInputs: {len(inputs)}")
    for inp in inputs:
        print(f"  {inp['name']}: dtype={inp['dtype']}, "
              f"dims={inp['dims']}, size={inp['size']}")

    print(f"\nOutputs: {len(outputs)}")
    for out in outputs:
        print(f"  {out['name']}: dtype={out['dtype']}, "
              f"dims={out['dims']}, size={out['size']}")

    rknn.release()


# ── 主函数 ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description='RKNN-Toolkit1 Model Exporter for RK3399Pro')
    parser.add_argument('--input', '-i', type=str,
                        help='Input model path (.pt for PyTorch, .onnx for ONNX)')
    parser.add_argument('--output', '-o', type=str,
                        help='Output RKNN model path')
    parser.add_argument('--type', type=str, default='yolov5',
                        choices=['yolov5', 'osnet'],
                        help='Model type (yolov5 or osnet)')
    parser.add_argument('--quantize', action='store_true',
                        help='Enable INT8 quantization')
    parser.add_argument('--calib-dir', type=str,
                        help='Calibration images directory for INT8')
    parser.add_argument('--platform', type=str, default='rk3399pro',
                        help='Target platform (default: rk3399pro)')
    parser.add_argument('--img-size', type=int, default=640,
                        help='Input image size (YOLOv5 only, default: 640)')
    parser.add_argument('--info', action='store_true',
                        help='Show model info only (no export)')
    parser.add_argument('--onnx-only', action='store_true',
                        help='Export ONNX only (skip RKNN conversion)')

    args = parser.parse_args()

    if not args.input:
        parser.print_help()
        sys.exit(1)

    # 查看模型信息
    if args.info:
        show_model_info(args.input)
        return

    # 确定输出路径
    if not args.output:
        base = os.path.splitext(args.input)[0]
        args.output = base + '.rknn'

    onnx_path = os.path.splitext(args.output)[0] + '.onnx'

    # Step 1: PyTorch → ONNX
    if args.input.endswith('.pt'):
        if args.type == 'yolov5':
            export_onnx_yolov5(args.input, onnx_path, args.img_size)
        elif args.type == 'osnet':
            export_onnx_osnet(args.input, onnx_path)
        else:
            print(f"Unknown model type: {args.type}")
            sys.exit(1)

        if args.onnx_only:
            print(f"ONNX exported to: {onnx_path}")
            return
    else:
        onnx_path = args.input

    # Step 2: ONNX → RKNN
    export_rknn(onnx_path, args.output,
                quantize=args.quantize,
                calib_dir=args.calib_dir,
                target_platform=args.platform)

    print(f"\nDone! RKNN model: {args.output}")
    print(f"Copy to device: scp {args.output} root@rk3399pro:/opt/edge-ai/models/")


if __name__ == '__main__':
    main()