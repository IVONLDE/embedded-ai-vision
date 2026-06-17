#!/bin/bash
# gRPC Code Generator Script
#
# 从 proto 文件生成 C++ 和 Python stub 代码。
#
# 用法: ./scripts/gen_proto.sh
#
# 依赖:
#   - protoc (protobuf compiler)
#   - grpc_cpp_plugin (gRPC C++ plugin)
#   - grpc_python_plugin (gRPC Python plugin)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROTO_DIR="${PROJECT_ROOT}/proto"
OUT_CPP="${PROJECT_ROOT}/src/comm/generated"
OUT_PY="${PROJECT_ROOT}/training/backend/services/generated"

echo "=== Proto Code Generation ==="

# 检查 protoc
if ! command -v protoc &> /dev/null; then
    echo "Error: protoc not found. Install:"
    echo "  sudo apt install protobuf-compiler"
    exit 1
fi

# 生成 C++ gRPC
echo ""
echo "[C++] Generating stubs from proto files..."

mkdir -p "${OUT_CPP}"

for proto in "${PROTO_DIR}"/*.proto; do
    fname=$(basename "${proto}")
    echo "  ${fname}"

    # Generate protobuf
    protoc \
        --proto_path="${PROTO_DIR}" \
        --cpp_out="${OUT_CPP}" \
        "${proto}"

    # Generate gRPC
    if command -v grpc_cpp_plugin &> /dev/null; then
        protoc \
            --proto_path="${PROTO_DIR}" \
            --grpc_out="${OUT_CPP}" \
            --plugin=protoc-gen-grpc="$(which grpc_cpp_plugin)" \
            "${proto}"
    else
        echo "    (skipping gRPC — grpc_cpp_plugin not found)"
    fi
done

echo "  → C++ stubs written to: ${OUT_CPP}"

# 生成 Python gRPC
echo ""
echo "[Python] Generating stubs..."

mkdir -p "${OUT_PY}"

for proto in "${PROTO_DIR}"/*.proto; do
    fname=$(basename "${proto}")
    echo "  ${fname}"

    # Generate protobuf
    protoc \
        --proto_path="${PROTO_DIR}" \
        --python_out="${OUT_PY}" \
        "${proto}"

    # Generate gRPC
    if command -v grpc_python_plugin &> /dev/null; then
        protoc \
            --proto_path="${PROTO_DIR}" \
            --grpc_python_out="${OUT_PY}" \
            --plugin=protoc-gen-grpc_python="$(which grpc_python_plugin)" \
            "${proto}"
    else
        echo "    (installing grpcio-tools for Python generation...)"
        python3 -c "from grpc_tools.protoc import main; main()" \
            --proto_path="${PROTO_DIR}" \
            --python_out="${OUT_PY}" \
            --grpc_python_out="${OUT_PY}" \
            "${proto}" 2>/dev/null || \
        echo "    (skipping Python gRPC — install with: pip install grpcio-tools)"
    fi
done

echo "  → Python stubs written to: ${OUT_PY}"
echo ""
echo "=== Proto generation complete ==="