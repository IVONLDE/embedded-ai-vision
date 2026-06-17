"""
Transformer模型
基于Transformer的时序预测模型，适合处理长序列依赖
"""
import torch
import torch.nn as nn
import math
from base_model import BaseTimeSeriesModel
import logging

logger = logging.getLogger(__name__)


class PositionalEncoding(nn.Module):
    """位置编码模块"""
    
    def __init__(self, d_model: int, max_len: int = 5000, dropout: float = 0.1):
        """
        初始化位置编码
        
        Args:
            d_model: 模型维度
            max_len: 最大序列长度
            dropout: Dropout比例
        """
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        # 创建位置编码矩阵
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        
        self.register_buffer('pe', pe)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        添加位置编码
        
        Args:
            x: 输入张量 (batch_size, seq_len, d_model)
            
        Returns:
            添加位置编码后的张量
        """
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class TransformerModel(BaseTimeSeriesModel):
    """Transformer时序预测模型"""
    
    def __init__(self,
                 input_dim: int,
                 output_dim: int,
                 lookback_window: int,
                 prediction_window: int,
                 d_model: int = 64,
                 nhead: int = 4,
                 num_layers: int = 2,
                 dim_feedforward: int = 256,
                 dropout: float = 0.2):
        """
        初始化Transformer模型
        
        Args:
            input_dim: 输入特征维度
            output_dim: 输出特征维度
            lookback_window: 回顾窗口长度
            prediction_window: 预测窗口长度
            d_model: Transformer模型维度
            nhead: 注意力头数
            num_layers: Transformer层数
            dim_feedforward: 前馈网络维度
            dropout: Dropout比例
        """
        super(TransformerModel, self).__init__(
            input_dim, output_dim, lookback_window, prediction_window
        )
        
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers
        self.dim_feedforward = dim_feedforward
        self.dropout = dropout
        
        # 输入嵌入层（将input_dim映射到d_model）
        self.input_embedding = nn.Linear(input_dim, d_model)
        
        # 位置编码
        self.pos_encoder = PositionalEncoding(d_model, max_len=lookback_window, dropout=dropout)
        
        # Transformer编码器
        encoder_layers = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True
        )
        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layers,
            num_layers=num_layers
        )
        
        # 输出解码器
        self.decoder = nn.Sequential(
            nn.Linear(d_model, dim_feedforward),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(dim_feedforward, prediction_window * output_dim)
        )
        
        logger.info(f"初始化Transformer模型 - d_model: {d_model}, "
                   f"注意力头数: {nhead}, 层数: {num_layers}")
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        Args:
            x: 输入张量 (batch_size, lookback_window, input_dim)
            
        Returns:
            输出张量 (batch_size, prediction_window, output_dim)
        """
        batch_size = x.size(0)
        
        # 输入嵌入
        x = self.input_embedding(x)  # (batch_size, lookback_window, d_model)
        x = x * math.sqrt(self.d_model)  # 缩放
        
        # 添加位置编码
        x = self.pos_encoder(x)
        
        # Transformer编码
        transformer_out = self.transformer_encoder(x)
        # (batch_size, lookback_window, d_model)
        
        # 使用最后一个时间步的输出或平均池化
        # 这里使用最后一个时间步
        last_output = transformer_out[:, -1, :]  # (batch_size, d_model)
        
        # 或者使用平均池化
        # last_output = transformer_out.mean(dim=1)  # (batch_size, d_model)
        
        # 解码到预测窗口
        output = self.decoder(last_output)  # (batch_size, prediction_window * output_dim)
        
        # 重塑为 (batch_size, prediction_window, output_dim)
        output = output.view(batch_size, self.prediction_window, self.output_dim)
        
        return output
    
    def get_model_info(self) -> dict:
        """获取模型详细信息"""
        info = super().get_model_info()
        info.update({
            'd_model': self.d_model,
            'nhead': self.nhead,
            'num_layers': self.num_layers,
            'dim_feedforward': self.dim_feedforward,
            'dropout': self.dropout
        })
        return info

