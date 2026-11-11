import os
import argparse
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
import mlflow
import mlflow.pytorch

# Simple LSTM model for multivariate time‑series forecasting
class SensorLSTM(nn.Module):
    def __init__(self, input_dim, hidden_dim, num_layers, output_dim, dropout=0.2):
        super(SensorLSTM, self).__init__()
        self.lstm = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_dim, output_dim)

    def forward(self, x):
        out, _ = self.lstm(x)
        # Take the last time step
        out = out[:, -1, :]
        return self.fc(out)

def load_data(s3_path: str, seq_len: int = 48):
    # Assume CSV with timestamp and sensor columns
    df = pd.read_csv(s3_path)
    df = df.sort_values('timestamp')
    sensor_cols = [c for c in df.columns if c != 'timestamp']
    data = df[sensor_cols].values
    X, y = [], []
    for i in range(len(data) - seq_len - 1):
        X.append(data[i:i+seq_len])
        y.append(data[i+seq_len])
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    return TensorDataset(torch.from_numpy(X), torch.from_numpy(y))

def train(args):
    mlflow.set_experiment('assembly-maintenance')
    with mlflow.start_run(run_name=args.run_name):
        mlflow.log_params({
            'seq_len': args.seq_len,
            'hidden_dim': args.hidden_dim,
            'num_layers': args.num_layers,
            'batch_size': args.batch_size,
            'lr': args.lr,
            'epochs': args.epochs
        })
        dataset = load_data(args.data_path, seq_len=args.seq_len)
        loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=True)
        model = SensorLSTM(input_dim=dataset.tensors[0].shape[2],
                           hidden_dim=args.hidden_dim,
                           num_layers=args.num_layers,
                           output_dim=dataset.tensors[0].shape[2])
        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
        for epoch in range(1, args.epochs + 1):
            model.train()
            epoch_loss = 0.0
            for xb, yb in loader:
                optimizer.zero_grad()
                preds = model(xb)
                loss = criterion(preds, yb)
                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * xb.size(0)
            epoch_rmse = np.sqrt(epoch_loss / len(dataset))
            mlflow.log_metric('rmse', epoch_rmse, step=epoch)
            print(f'Epoch {epoch}/{args.epochs} – RMSE: {epoch_rmse:.4f}')
        # Log the model artifact
        mlflow.pytorch.log_model(model, 'model')
        # Optionally push Docker image for SageMaker (handled in separate script)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train LSTM for predictive maintenance')
    parser.add_argument('--data-path', type=str, required=True, help='S3 path to cleaned CSV')
    parser.add_argument('--run-name', type=str, default='lstm-run')
    parser.add_argument('--seq-len', type=int, default=48)
    parser.add_argument('--hidden-dim', type=int, default=128)
    parser.add_argument('--num-layers', type=int, default=2)
    parser.add_argument('--batch-size', type=int, default=64)
    parser.add_argument('--lr', type=float, default=1e-3)
    parser.add_argument('--epochs', type=int, default=20)
    train(parser.parse_args())
