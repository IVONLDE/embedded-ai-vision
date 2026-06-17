import torch
import torch.nn as nn
from torchvision.models import resnet34

    
class ConvBlock(nn.Module):
    def __init__(self, in_channel, out_channel):
        super(ConvBlock, self).__init__()
        
        self.network = nn.Sequential(
            nn.Conv1d(in_channel, out_channel, kernel_size=3, padding=1),
            nn.BatchNorm1d(out_channel),
            nn.PReLU()
        )
        
    def forward(self, x):
        output = self.network(x)
        
        return output
    
    
class Raw_Signal_Convolution_Block(nn.Module):
    def __init__(self, ):
        super(Raw_Signal_Convolution_Block, self).__init__()
        
        self.network = nn.Sequential(
            ConvBlock(1, 2),
            ConvBlock(2, 4),
            ConvBlock(4, 8),
            ConvBlock(8, 16),
            ConvBlock(16, 32),
            ConvBlock(32, 64),
        )
        
    def forward(self, x):
        output = self.network(x)
        return output
    

class Raw_Signal_Feature_Extractor(nn.Module):
    def __init__(self, imaging, classify_model):
        super(Raw_Signal_Feature_Extractor, self).__init__()
        self.imaging = imaging
        self.classify_model = classify_model
        
    def forward(self, x):
        out = self.imaging(x)
        out = out.unsqueeze(1)
        out = self.classify_model(out)
        return out