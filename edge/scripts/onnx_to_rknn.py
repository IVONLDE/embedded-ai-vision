#!/usr/bin/env python3
"""
ONNX → RKNN 转换脚本 (板子端)

在 RK3399Pro 板子上将 ONNX 模型转换为 RKNN 格式。
使用 rknn-toolkit-lite (板子端轻量版) 或 rknn-toolkit (完整版)。

用法:
    python3 onnx_to_rknn.py --input model.onnx --output model.rknn
    python3 onnx_to_rknn.py --input model.onnx --output model.rknn --quantize --calib-dir /opt/edge-ai/calib
    python3 onnx_to_rknn.py --input model.onnx --info   # 查看模型信息
"""
import argparse
import os
import sys

def convert_onnx_to_rknn(onnx_path, rknn_path,
                          quantize=False, calib_dir=None,
                          target_platform="rk3399pro"):
    """将 ONNX 模型转换为 RKNN 格式"""
    # 优先用 rknn-toolkit-lite (板子端轻量版)
    try:
        from rknnlite.api import RKNNLite as RKNN
        print("[ONNX→RKNN] 使用 rknn-toolkit-lite")
    except ImportError:
        try:
            from rknn.api import RKNN
            print("[ONNX→RKNN] 使用 rknn-toolkit")
        except ImportError:
            print("Error: rknn-toolkit-lite 和 rknn-toolkit 都未安装")
            sys.exit(1)

    if not os.path.exists(onnx_path):
        print(f"Error: ONNX 文件不存在: {onnx_path}")
        sys.exit(1)

    rknn = RKNN()

    # 配置
    print(f"[ONNX→RKNN] 目标平台: {target_platform}")
    rknn.config(
        mean_values=[[0, 0, 0]],
        std_values=[[255, 255, 255]],
        reorder_channel='0 1 2',
        target_platform=target_platform,
        optimization_level=3
    )

    # 加载 ONNX
    print(f"[ONNX→RKNN] 加载 ONNX: {onnx_path}")
    ret = rknn.load_onnx(model=onnx_path)
    if ret != 0:
        print(f"[ONNX→RKNN] 加载 ONNX 失败: {ret}")
        sys.exit(1)

    # 构建
    print("[ONNX→RKNN] 构建模型...")
    ret = rknn.build(do_quantization=quantize)
    if ret != 0:
        print(f"[ONNX→RKNN] 构建失败: {ret}")
        sys.exit(1)

    # INT8 量化校准
    if quantize and calib_dir:
        import cv2
        import numpy as np
        print(f"[ONNX→RKNN] INT8 校准数据: {calib_dir}")
        calib_images = []
        for fname in sorted(os.listdir(calib_dir))[:200]:
            if fname.lower().endswith(('.jpg', '.jpeg', '.png')):
                calib_images.append(os.path.join(calib_dir, fname))

        if calib_images:
            for idx, img_path in enumerate(calib_images[:100]):
                img = cv2.imread(img_path)
                if img is None:
                    continue
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                img = cv2.resize(img, (640, 640))
                img = img.astype(np.float32) / 255.0
                img = np.expand_dims(img, axis=0)
                rknn.inference(inputs=[img])
                if (idx + 1) % 20 == 0:
                    print(f"  校准进度: {idx + 1}/{min(len(calib_images), 100)}")
            print(f"[ONNX→RKNN] 校准完成, 使用 {min(len(calib_images), 100)} 张图片")
        else:
            print("[ONNX→RKNN] 警告: 未找到校准图片, INT8 精度可能较差")

    # 导出
    print(f"[ONNX→RKNN] 导出 RKNN: {rknn_path}")
    ret = rknn.export_rknn(rknn_path)
    if ret != 0:
        print(f"[ONNX→RKNN] 导出失败: {ret}")
        sys.exit(1)

    file_size = os.path.getsize(rknn_path)
    print(f"[ONNX→RKNN] 转换完成: {rknn_path} ({file_size} bytes)")
    rknn.release()


def show_onnx_info(onnx_path):
    """查看 ONNX 模型信息"""
    import onnx
    model = onnx.load(onnx_path)
    print(f"\n=== ONNX 模型: {onnx_path} ===")
    print(f"IR 版本: {model.ir_version}")
    print(f"Opset 版本: {[o.version for o in model.opset_import]}")

    print(f"\n输入:")
    for inp in model.graph.input:
        shape = [d.dim_value for d in inp.type.tensor_type.shape.dim]
        print(f"  {inp.name}: shape={shape}")

    print(f"\n输出:")
    for out in model.graph.output:
        shape = [d.dim_value for d in out.type.tensor_type.shape.dim]
        print(f"  {out.name}: shape={shape}")


def main():
    parser = argparse.ArgumentParser(description='ONNX → RKNN 转换 (RK3399Pro 板子端)')
    parser.add_argument('--input', '-i', type=str, required=True,
                        help='输入 ONNX 模型路径')
    parser.add_argument('--output', '-o', type=str,
                        help='输出 RKNN 模型路径 (默认: 同名.rknn)')
    parser.add_argument('--quantize', action='store_true',
                        help='启用 INT8 量化')
    parser.add_argument('--calib-dir', type=str,
                        help='INT8 校准图片目录')
    parser.add_argument('--platform', type=str, default='rk3399pro',
                        help='目标平台 (默认: rk3399pro)')
    parser.add_argument('--info', action='store_true',
                        help='仅查看模型信息 (不转换)')

    args = parser.parse_args()

    if args.info:
        show_onnx_info(args.input)
        return

    if not args.output:
        args.output = os.path.splitext(args.input)[0] + '.rknn'

    convert_onnx_to_rknn(
        args.input, args.output,
        quantize=args.quantize,
        calib_dir=args.calib_dir,
        target_platform=args.platform
    )

    print(f"\n完成! RKNN 模型: {args.output}")


if __name__ == '__main__':
    main()
