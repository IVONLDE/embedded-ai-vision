import pandas as pd
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.model_selection import train_test_split


def timeseries_to_DataFrame(df, window_size, stride):
    #df = pd.read_csv('./dataset/time_series_dataframe.csv')
    cols = list()
    names = [('t-%d' % (j)) for j in range(window_size, 0, -1)]
    names += ['label']
    for i in range(0, len(df) - window_size, stride):
        temp_data = df.iloc[i : i+window_size, 0].values
        label_data = df.iloc[i : i+window_size, 1].values
        if max(label_data) == min(label_data):
            label = int(min(label_data))
            tmp_data = np.append(temp_data, label)
            cols.append(tmp_data)
        
    new_df = pd.DataFrame(cols, columns = names)
    return new_df