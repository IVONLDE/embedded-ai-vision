"""
基础模型类
定义所有时序预测模型的通用接口
"""
import torch
import torch.nn as nn
from abc import ABC, abstractmethod
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class BaseTimeSeriesModel(nn.Module, ABC):
    """时序预测模型基类"""
    
    def __init__(self, 
                 input_dim: int,
                 output_dim: int,
                 lookback_window: int,
                 prediction_window: int):
        """
        初始化基础模型
        
        Args:
            input_dim: 输入特征维度
            output_dim: 输出特征维度
            lookback_window: 回顾窗口长度
            prediction_window: 预测窗口长度
        """
        super(BaseTimeSeriesModel, self).__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.lookback_window = lookback_window
        self.prediction_window = prediction_window
        
    @abstractmethod
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        前向传播
        
        Args:
            x: 输入张量 (batch_size, lookback_window, input_dim)
            
        Returns:
            输出张量 (batch_size, prediction_window, output_dim)
        """
        pass
    
    def get_model_info(self) -> Dict[str, Any]:
        """
        获取模型信息
        
        Returns:
            包含模型配置的字典
        """
        return {
            'model_type': self.__class__.__name__,
            'input_dim': self.input_dim,
            'output_dim': self.output_dim,
            'lookback_window': self.lookback_window,
            'prediction_window': self.prediction_window,
            'num_parameters': sum(p.numel() for p in self.parameters()),
            'trainable_parameters': sum(p.numel() for p in self.parameters() if p.requires_grad)
        }
    
    def save_model(self, path: str):
        """
        保存模型
        
        Args:
            path: 保存路径
        """
        torch.save({
            'model_state_dict': self.state_dict(),
            'model_config': self.get_model_info()
        }, path)
        logger.info(f"模型已保存到 {path}")
    
    def load_model(self, path: str, device: str = 'cpu'):
        """
        加载模型
        
        Args:
            path: 模型路径
            device: 设备（'cpu' 或 'cuda'）
        """
        checkpoint = torch.load(path, map_location=device)
        self.load_state_dict(checkpoint['model_state_dict'])
        logger.info(f"模型已从 {path} 加载")
        return checkpoint.get('model_config', {})

