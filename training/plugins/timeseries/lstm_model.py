"""
LSTM模型
基于LSTM的时序预测模型，适合捕捉长期依赖关系
"""
import torch
import torch.nn as nn
from base_model import BaseTimeSeriesModel
import logging

logger = logging.getLogger(__name__)


class LSTMModel(BaseTimeSeriesModel):
    """LSTM时序预测模型"""
    
    def __init__(self,
                 input_dim: int,
                 output_dim: int,
                 lookback_window: int,
                 prediction_window: int,
                 hidden_size: int = 64,
                 num_layers: int = 2,
                 dropout: float = 0.2,
                 bidirectional: bool = False):
        """
        初始化LSTM模型
        
        Args:
            input_dim: 输入特征维度
            output_dim: 输出特征维度
            lookback_window: 回顾窗口长度
            prediction_window: 预测窗口长度
            hidden_size: LSTM隐藏层大小
            num_layers: LSTM层数
            dropout: Dropout比例
            bidirectional: 是否使用双向LSTM
        """
        super(LSTMModel, self).__init__(
            input_dim, output_dim, lookback_window, prediction_window
        )
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.bidirectional = bidirectional
        
        # LSTM层
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional
        )
        
        # Batch Normalization（稳定训练）
        self.batch_norm = nn.BatchNorm1d(lookback_window)
        
        # Dropout层
        self.dropout_layer = nn.Dropout(dropout)
        
        # 全连接输出层
        lstm_output_size = hidden_size * 2 if bidirectional else hidden_size
        
        # 时序解码器：将LSTM输出映射到预测窗口
        self.decoder = nn.Sequential(
            nn.Linear(lstm_output_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, prediction_window * output_dim)
        )
        
        logger.info(f"初始化LSTM模型 - 隐藏层大小: {hidden_size}, "
                   f"层数: {num_layers}, 双向: {bidirectional}")
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        Args:
            x: 输入张量 (batch_size, lookback_window, input_dim)
            
        Returns:
            输出张量 (batch_size, prediction_window, output_dim)
        """
        batch_size = x.size(0)
        
        # Batch Normalization
        x = self.batch_norm(x)
        
        # LSTM层
        lstm_out, (hidden, cell) = self.lstm(x)
        # lstm_out: (batch_size, lookback_window, hidden_size * num_directions)
        
        # 取最后一个时间步的输出
        last_output = lstm_out[:, -1, :]  # (batch_size, hidden_size * num_directions)
        
        # Dropout
        last_output = self.dropout_layer(last_output)
        
        # 解码到预测窗口
        output = self.decoder(last_output)  # (batch_size, prediction_window * output_dim)
        
        # 重塑为 (batch_size, prediction_window, output_dim)
        output = output.view(batch_size, self.prediction_window, self.output_dim)
        
        return output
    
    def get_model_info(self) -> dict:
        """获取模型详细信息"""
        info = super().get_model_info()
        info.update({
            'hidden_size': self.hidden_size,
            'num_layers': self.num_layers,
            'dropout': self.dropout,
            'bidirectional': self.bidirectional
        })
        return info


class GRUModel(BaseTimeSeriesModel):
    """GRU时序预测模型（LSTM的轻量级替代）"""
    
    def __init__(self,
                 input_dim: int,
                 output_dim: int,
                 lookback_window: int,
                 prediction_window: int,
                 hidden_size: int = 64,
                 num_layers: int = 2,
                 dropout: float = 0.2,
                 bidirectional: bool = False):
        """初始化GRU模型"""
        super(GRUModel, self).__init__(
            input_dim, output_dim, lookback_window, prediction_window
        )
        
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.bidirectional = bidirectional
        
        # GRU层
        self.gru = nn.GRU(
            input_size=input_dim,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=bidirectional
        )
        
        self.batch_norm = nn.BatchNorm1d(lookback_window)
        self.dropout_layer = nn.Dropout(dropout)
        
        gru_output_size = hidden_size * 2 if bidirectional else hidden_size
        
        self.decoder = nn.Sequential(
            nn.Linear(gru_output_size, hidden_size),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_size, prediction_window * output_dim)
        )
        
        logger.info(f"初始化GRU模型 - 隐藏层大小: {hidden_size}, 层数: {num_layers}")
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向传播"""
        batch_size = x.size(0)
        
        x = self.batch_norm(x)
        gru_out, hidden = self.gru(x)
        
        last_output = gru_out[:, -1, :]
        last_output = self.dropout_layer(last_output)
        
        output = self.decoder(last_output)
        output = output.view(batch_size, self.prediction_window, self.output_dim)
        
        return output

