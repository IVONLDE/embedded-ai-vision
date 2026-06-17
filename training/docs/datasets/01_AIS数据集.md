# AIS 数据集 (AIS Dataset)

> 路径: `F:\716数据集\AIS数据集`
> 状态: ⚠️ 部分文件处于下载中/未完成状态

---

## 数据集概览

AIS（Automatic Identification System，船舶自动识别系统）数据集包含船舶航行轨迹数据，可用于船舶行为分析、航迹预测、异常检测等任务。

## 包含子集

| 子集 | 说明 | 状态 |
|------|------|------|
| **AegeaNET Syros AIS Dataset** | 希腊锡罗斯岛海域 AIS 数据，附带 AudioClassification-Pytorch 音频分类参考代码 | `.xltd` 未完成 |
| **AIS Dataset** | AIS 原始数据包 | `.baiduyun.p.downloading` 下载中 |

## 数据格式

AIS 数据通常包含以下字段：
- `longitude` / `latitude`: 船舶经纬度
- `speed`: 航速 (节)
- `course`: 航向 (度)
- `timestamp`: 时间戳
- `mmsi`: 船舶唯一标识
- `vessel_type`: 船舶类型

## 可实现的深度学习算法

### 1. 航迹预测 (Trajectory Prediction)
- **LSTM / GRU**: 序列建模预测船舶未来位置
- **Transformer**: 基于自注意力的长序列航迹预测
- **Social-LSTM**: 考虑多船交互的轨迹预测

### 2. 船舶行为分类 (Vessel Behavior Classification)
- **CNN + LSTM**: 从轨迹段提取时空特征，分类航行行为（捕鱼、锚泊、航行等）
- **1D-CNN**: 滑动窗口提取局部航行模式

### 3. 异常检测 (Anomaly Detection)
- **AutoEncoder**: 重构误差检测异常航迹
- **Isolation Forest + 时序特征**: 偏离正常航道的船舶检测
- **GNN (图神经网络)**: 基于船舶交互图的群体异常检测

### 4. 船舶类型识别 (Vessel Type Classification)
- **随机森林 / XGBoost**: 基于航行特征的传统 ML 分类
- **MLP**: 深度全连接分类器

### 5. 到达时间预测 (ETA Prediction)
- **Seq2Seq**: 编码航行历史，解码剩余航行时间
- **Temporal Fusion Transformer**: 融合多变量时序的 ETA 预测

---

## 参考论文方向

- Deep Learning for Vessel Trajectory Prediction
- AIS-based Maritime Anomaly Detection
- Transformer Networks for Trajectory Forecasting
