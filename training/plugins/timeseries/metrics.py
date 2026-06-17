"""
评估指标模块
提供各种时序预测评估指标
"""
import numpy as np
import torch
from typing import Union


def calculate_mae(y_true: Union[np.ndarray, torch.Tensor], 
                  y_pred: Union[np.ndarray, torch.Tensor]) -> float:
    """
    计算平均绝对误差 (MAE)
    
    Args:
        y_true: 真实值
        y_pred: 预测值
        
    Returns:
        MAE值
    """
    if isinstance(y_true, torch.Tensor):
        y_true = y_true.detach().cpu().numpy()
    if isinstance(y_pred, torch.Tensor):
        y_pred = y_pred.detach().cpu().numpy()
    
    return np.mean(np.abs(y_true - y_pred))


def calculate_rmse(y_true: Union[np.ndarray, torch.Tensor],
                   y_pred: Union[np.ndarray, torch.Tensor]) -> float:
    """
    计算均方根误差 (RMSE)
    
    Args:
        y_true: 真实值
        y_pred: 预测值
        
    Returns:
        RMSE值
    """
    if isinstance(y_true, torch.Tensor):
        y_true = y_true.detach().cpu().numpy()
    if isinstance(y_pred, torch.Tensor):
        y_pred = y_pred.detach().cpu().numpy()
    
    return np.sqrt(np.mean((y_true - y_pred) ** 2))


def calculate_mape(y_true: Union[np.ndarray, torch.Tensor],
                   y_pred: Union[np.ndarray, torch.Tensor],
                   epsilon: float = 1e-10) -> float:
    """
    计算平均绝对百分比误差 (MAPE)
    
    Args:
        y_true: 真实值
        y_pred: 预测值
        epsilon: 避免除零的小常数
        
    Returns:
        MAPE值（百分比）
    """
    if isinstance(y_true, torch.Tensor):
        y_true = y_true.detach().cpu().numpy()
    if isinstance(y_pred, torch.Tensor):
        y_pred = y_pred.detach().cpu().numpy()
    
    return np.mean(np.abs((y_true - y_pred) / (np.abs(y_true) + epsilon))) * 100


def calculate_r2_score(y_true: Union[np.ndarray, torch.Tensor],
                       y_pred: Union[np.ndarray, torch.Tensor]) -> float:
    """
    计算R²分数
    
    Args:
        y_true: 真实值
        y_pred: 预测值
        
    Returns:
        R²分数
    """
    if isinstance(y_true, torch.Tensor):
        y_true = y_true.detach().cpu().numpy()
    if isinstance(y_pred, torch.Tensor):
        y_pred = y_pred.detach().cpu().numpy()
    
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    
    return 1 - (ss_res / (ss_tot + 1e-10))


def calculate_distance_error(lon_true: np.ndarray,
                             lat_true: np.ndarray,
                             lon_pred: np.ndarray,
                             lat_pred: np.ndarray) -> float:
    """
    计算地理距离误差（单位：公里）
    使用Haversine公式
    
    Args:
        lon_true: 真实经度
        lat_true: 真实纬度
        lon_pred: 预测经度
        lat_pred: 预测纬度
        
    Returns:
        平均距离误差（公里）
    """
    # 地球半径（公里）
    R = 6371.0
    
    # 转换为弧度
    lon_true_rad = np.radians(lon_true)
    lat_true_rad = np.radians(lat_true)
    lon_pred_rad = np.radians(lon_pred)
    lat_pred_rad = np.radians(lat_pred)
    
    # Haversine公式
    dlon = lon_pred_rad - lon_true_rad
    dlat = lat_pred_rad - lat_true_rad
    
    a = np.sin(dlat/2)**2 + np.cos(lat_true_rad) * np.cos(lat_pred_rad) * np.sin(dlon/2)**2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
    
    distance = R * c
    
    return np.mean(distance)


def evaluate_all_metrics(y_true: Union[np.ndarray, torch.Tensor],
                        y_pred: Union[np.ndarray, torch.Tensor]) -> dict:
    """
    计算所有评估指标
    
    Args:
        y_true: 真实值
        y_pred: 预测值
        
    Returns:
        包含所有指标的字典
    """
    metrics = {
        'MAE': calculate_mae(y_true, y_pred),
        'RMSE': calculate_rmse(y_true, y_pred),
        'MAPE': calculate_mape(y_true, y_pred),
        'R2': calculate_r2_score(y_true, y_pred)
    }
    
    # 如果是位置预测（2维输出：经度+纬度）
    if isinstance(y_true, torch.Tensor):
        y_true = y_true.detach().cpu().numpy()
    if isinstance(y_pred, torch.Tensor):
        y_pred = y_pred.detach().cpu().numpy()
    
    if y_true.shape[-1] == 2:
        # 假设第一维是经度，第二维是纬度
        lon_true = y_true[..., 0].flatten()
        lat_true = y_true[..., 1].flatten()
        lon_pred = y_pred[..., 0].flatten()
        lat_pred = y_pred[..., 1].flatten()
        
        metrics['Distance_Error_km'] = calculate_distance_error(
            lon_true, lat_true, lon_pred, lat_pred
        )
    
    return metrics

