# 贡献指南

感谢你对 embedded-ai-vision 项目的关注！本文档介绍如何参与项目贡献。

## 快速开始

### 1. Fork 仓库

在 GitHub 上 Fork [IVONLDE/embedded-ai-vision](https://github.com/IVONLDE/embedded-ai-vision)，然后克隆到本地：

```bash
git clone git@github.com:<你的用户名>/embedded-ai-vision.git
cd embedded-ai-vision
git remote add upstream git@github.com:IVONLDE/embedded-ai-vision.git
```

### 2. 创建特性分支

```bash
git checkout -b feature/amazing-feature
# 或
git checkout -b fix/bug-description
```

### 3. 开发与测试

参考 [DEVELOPMENT.md](docs/DEVELOPMENT.md) 搭建开发环境，编写代码和测试。

### 4. 提交代码

```bash
git add .
git commit -m "feat: 简洁描述你的变更"
```

### 5. 推送并创建 PR

```bash
git push origin feature/amazing-feature
```

在 GitHub 上创建 Pull Request，描述你的变更内容和动机。

## 贡献方式

### 报告 Bug

1. 在 [Issues](https://github.com/IVONLDE/embedded-ai-vision/issues) 中搜索是否已有相同问题
2. 如果没有，创建新 Issue，包含：
   - **环境信息**：硬件型号、OS 版本、内核版本
   - **复现步骤**：详细描述如何触发 Bug
   - **期望行为**：应该发生什么
   - **实际行为**：实际发生了什么
   - **日志**：相关的 `dmesg`/`journalctl` 输出

### 提出新功能

1. 创建 Issue，描述：
   - **需求背景**：为什么需要这个功能
   - **功能描述**：具体要实现什么
   - **适用场景**：哪些场景会用到
2. 等待维护者反馈后再开始开发

### 提交代码

- 遵循项目的代码规范（见 [DEVELOPMENT.md](docs/DEVELOPMENT.md)）
- 每个 PR 只做一件事（单一职责）
- 新功能需要包含测试
- Bug 修复需要包含回归测试

## 代码审查标准

### 必须通过

- [ ] 代码编译通过（C++ `cmake && make`，Python `import` 正常）
- [ ] 测试通过（`pytest tests/ -v`）
- [ ] 不引入新的编译警告
- [ ] 遵循现有代码风格
- [ ] 中文领域逻辑注释，英文代码标识符

### 建议满足

- [ ] 新功能有文档更新
- [ ] 公开 API 有类型注解/注释
- [ ] 考虑了错误处理和边界情况
- [ ] 没有不必要的抽象或过度设计

## 提交规范

### Commit Message 格式

```
<type>: <简短描述>

[可选的详细说明]
```

**Type 类型**：

| Type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | Bug 修复 |
| `docs` | 文档更新 |
| `refactor` | 代码重构（不改变功能） |
| `perf` | 性能优化 |
| `test` | 测试相关 |
| `build` | 构建系统变更 |
| `ci` | CI 配置变更 |
| `chore` | 杂项（依赖更新等） |

**示例**：

```
feat: 添加 ByteTrack 跟踪算法支持

实现 ByteTrack 作为 SORT 的替代方案，支持低置信度检测框的二次匹配。
在 pipeline.yaml 中通过 tracking.algorithm 字段选择算法。

Closes #42
```

### PR 标题

与 commit message 格式一致：`feat: ...` / `fix: ...`

### PR 描述模板

```markdown
## 变更说明
简要描述这个 PR 做了什么。

## 变更类型
- [ ] 新功能
- [ ] Bug 修复
- [ ] 重构
- [ ] 文档
- [ ] 性能优化

## 测试
描述如何测试你的变更：

1. ...

## 关联 Issue
Closes #xxx
```

## 开发者必备知识

### RK3399Pro 架构基础

- 6 核 CPU：2×A72 (大核, CPU4/5) + 4×A53 (小核, CPU0-3)
- NPU：RK1808 IP Core，3.0 TOPS INT8
- 内存：LPDDR4 2-4GB，NPU CMA 保留 512MB
- 详见 [NPU_REFERENCE.md](docs/NPU_REFERENCE.md)

### 项目架构

- 五层架构：Buildroot → 内核驱动 → GStreamer → C++ 推理 → Python 管控
- 边缘端 C++ 四线程流水线：采集 → 推理 → 跟踪 → 输出
- PC 端 Python 分层架构：QML → BackendService → Services → Repositories → ORM
- 详见 [ARCHITECTURE.md](docs/ARCHITECTURE.md) 和 [BACKEND_ARCHITECTURE.md](training/docs/BACKEND_ARCHITECTURE.md)

### 通信协议

- gRPC：模型推送、场景切换、状态查询
- MQTT：检测结果上报、心跳、远程指令
- 详见 [PROTOCOL.md](docs/PROTOCOL.md)

## 行为准则

- 尊重所有贡献者
- 建设性的讨论和反馈
- 关注问题本身，不针对个人
- 欢迎 constructive criticism
