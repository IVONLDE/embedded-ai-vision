import torch
from torch import nn


class FC_Block(nn.Module):
    def __init__(self, in_features, out_features):
        super().__init__()
        self.fc = nn.Linear(in_features, out_features)
        self.relu = nn.PReLU()
    def forward(self, x):
        output = self.relu(self.fc(x))
        return output
    

class Spatial_Attention(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc_block_1_1 = FC_Block(6, 6)
        self.fc_block_1_2 = FC_Block(6, 6)
        self.fc_1_last = nn.Linear(6, 3)

        self.fc_block_2_1 = FC_Block(3, 3)
        self.fc_block_2_2 = FC_Block(3, 3)
        self.fc_2_last = nn.Linear(3, 6)

        self.fc_block_3_1 = FC_Block(6, 6)
        self.fc_block_3_2 = FC_Block(6, 6)
        self.fc_3_last = nn.Linear(6, 6)

        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        y = self.fc_1_last(self.fc_block_1_2(self.fc_block_1_1(x)))
        y = self.fc_2_last(self.fc_block_2_2(self.fc_block_2_1(y)))
        y = self.fc_3_last(self.fc_block_3_2(self.fc_block_3_1(y)))
        y = self.sigmoid(y)
        output = x * y
        return output
    

class Channel_Attention(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc_block_1_1 = FC_Block(12, 12)
        self.fc_block_1_2 = FC_Block(12, 12)
        self.fc_1_last = nn.Linear(12, 6)

        self.fc_block_2_1 = FC_Block(6, 6)
        self.fc_block_2_2 = FC_Block(6, 6)
        self.fc_2_last = nn.Linear(6, 4)

        self.fc_block_3_1 = FC_Block(4, 4)
        self.fc_block_3_2 = FC_Block(4, 4)
        self.fc_3_last = nn.Linear(4, 2)

        self.sigmoid = nn.Sigmoid()
        
    def forward(self, x):
        bs, _, _ = x.shape
        
        ws = x.reshape(bs, -1)
        ws = self.fc_1_last(self.fc_block_1_2(self.fc_block_1_1(ws)))
        ws = self.fc_2_last(self.fc_block_2_2(self.fc_block_2_1(ws)))
        ws = self.fc_3_last(self.fc_block_3_2(self.fc_block_3_1(ws)))
        ws = self.sigmoid(ws)

        output = x * ws.unsqueeze(dim=-1)

        return output
    

class Method(nn.Module):
    def __init__(self, tdf_module, raw_module):
        super().__init__()
        self.tdf_module = tdf_module
        self.raw_module = raw_module

        self.SA_tdf = Spatial_Attention()
        self.SA_raw = Spatial_Attention()

        self.CA = Channel_Attention()

        self.fc_out = nn.Linear(6, 6)

    def forward(self, x_tdf, x_raw):
       
        y_tdf = self.tdf_module(x_tdf)
        y_raw = self.raw_module(x_raw)

        y_tdf = self.SA_tdf(y_tdf)
        y_raw = self.SA_raw(y_raw)
        
        x_CA = torch.cat([y_tdf.unsqueeze(dim=1), y_raw.unsqueeze(dim=1)], dim=1)

        y_CA = (self.CA(x_CA))

        bs, _, _ = y_CA.shape

        y_CA = torch.sum(y_CA, dim=1, keepdim=True)
        
        output = self.fc_out(y_CA.reshape(bs, -1))
        
        return output