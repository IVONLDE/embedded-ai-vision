import torch
import torch.nn as nn


class TDF_Extractor(nn.Module):
    def __init__(self):
        super(TDF_Extractor, self).__init__()

        self.conv_1_1 = nn.Conv1d(12, 32, 1)
        self.conv_1_2 = nn.Conv1d(32, 32, 1)
        self.conv_1_3 = nn.Conv1d(32, 32, 1)

        self.conv_2_1 = nn.Conv1d(32, 64, 1)
        self.conv_2_2 = nn.Conv1d(64, 64, 1)
        self.conv_2_3 = nn.Conv1d(64, 64, 1)

        self.conv_3_1 = nn.Conv1d(64, 128, 1)
        self.conv_3_2 = nn.Conv1d(128, 128, 1)
        self.conv_3_3 = nn.Conv1d(128, 128, 1)

        self.conv_4_1 = nn.Conv1d(128, 256, 1)
        self.conv_4_2 = nn.Conv1d(256, 256, 1)
        self.conv_4_3 = nn.Conv1d(256, 256, 1)

        self.conv_5_1 = nn.Conv1d(256, 512, 1)
        self.conv_5_2 = nn.Conv1d(512, 512, 1)
        self.conv_5_3 = nn.Conv1d(512, 512, 1)

        self.fc_res_1_1 = nn.Linear(512, 256)
        self.fc_res_1_2 = nn.Linear(256, 512)

        self.fc_res_2_1 = nn.Linear(512, 256)
        self.fc_res_2_2 = nn.Linear(256, 512)
        
        self.fc_res_3_1 = nn.Linear(512, 256)
        self.fc_res_3_2 = nn.Linear(256, 512)

        self.fc_last = nn.Linear(512, 6)

        self.act = nn.ReLU()
        self.tanh = nn.Tanh()

        self.batch_norm_1 = nn.BatchNorm1d(num_features=32)
        self.batch_norm_2 = nn.BatchNorm1d(num_features=64)
        self.batch_norm_3 = nn.BatchNorm1d(num_features=128)
        self.batch_norm_4 = nn.BatchNorm1d(num_features=256)
        self.batch_norm_5 = nn.BatchNorm1d(num_features=512)

        self.layer_norm = nn.LayerNorm(512)
        
        self.dropout = nn.Dropout(0.9)


    def forward(self, x):
        bs, ch, n = x.shape

        x = x.permute(0, 2, 1).contiguous()

        x = self.act(self.conv_1_1(x))
        x = self.act(self.conv_1_2(x))
        x = self.batch_norm_1(self.act(self.conv_1_3(x)))

        x = self.act(self.conv_2_1(x))
        x = self.act(self.conv_2_2(x))
        x = self.batch_norm_2(self.act(self.conv_2_3(x)))

        x = self.act(self.conv_3_1(x))
        x = self.act(self.conv_3_2(x))
        x = self.batch_norm_3(self.act(self.conv_3_3(x)))

        x = self.act(self.conv_4_1(x))
        x = self.act(self.conv_4_2(x))
        x = self.batch_norm_4(self.act(self.conv_4_3(x)))

        x = self.act(self.conv_5_1(x))
        x = self.act(self.conv_5_2(x))
        x = self.batch_norm_5(self.act(self.conv_5_3(x)))

        x = x.permute(0, 2, 1).contiguous()

        x = x.reshape(bs, -1)

        xx = self.dropout(self.act(self.fc_res_1_1(x)))
        xx = self.fc_res_1_2(xx)
        x = x + xx
        x = self.layer_norm(self.act(x))

        xx = self.dropout(self.act(self.fc_res_2_1(x)))
        xx = self.fc_res_2_2(xx)
        x = x + xx
        x = self.layer_norm(self.act(x))

        xx = self.dropout(self.act(self.fc_res_3_1(x)))
        xx = self.fc_res_3_2(xx)
        x = x + xx
        x = self.layer_norm(self.act(x))

        x = self.fc_last(x)

        return x