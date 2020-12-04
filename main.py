import os
import time
from argparse import ArgumentParser
from utils import load_data

import numpy as np
import scipy.sparse as ssp
import torch
import torch.optim as optim
import torch.functional as F

from .summGCN import SummGCN
from utils import load_data, accuracy

parser = ArgumentParser()
parser.add_argument("--dataset", required=True, type=str,
                    help="Dataset name.")
parser.add_argument("--cuda", type=int, default=-1,
                    help="GPU id(-1 to use cpu).")
parser.add_argument("--seed", type=int, default=42,
                    help="Random seed.")
parser.add_argument("--epochs", type=int, default=200,
                    help="Number of epochs to train.")
parser.add_argument("--lr", type=float, default=0.01,
                    help="Initial learning rate.")
parser.add_argument("--weight_decay", type=float, default=5e-4,
                    help="Weight decay (L2 loss on parameters).")
parser.add_argument("--hidden", type=int, default=16,
                    help="Number of hidden units.")
parser.add_argument("--dropout", type=float, default=0.5,
                    help="Dropout rate (1 - keep probability).")
args = parser.parse_args()

gpu_id = args.cuda
if not torch.cuda.is_available():
    gpu_id = -1
np.random.seed(args.seed)
torch.manual_seed(args.seed)

R, S, features, labels, idx_train, idx_val, idx_test = load_data(args.dataset)
features_summ = S.T @ features
N, d = features.shape
n = S.shape[0]
nclass = labels.max().item() + 1
print(f"Dataset loaded. N: {N}, n: {n}, feature: {d}-dim")

if gpu_id >= 0:
    device = f"cuda:{gpu_id}"
    R = R.cuda(device)
    S = S.cuda(device)
    features_summ = features_summ.cuda(device)
    labels = labels.cuda(device)
    idx_train = idx_train.cuda(device)
    idx_val = idx_val.cuda(device)
    idx_test = idx_test.cuda(device)

model = SummGCN(d, args.hidden, nclass, dropout=args.dropout)


def train(model, epochs):
    optimizer = optim.Adam(model.parameters(),
                           lr=args.lr, weight_decay=args.weight_decay)
    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = model(features_summ, R)

        loss_train = F.nll_loss(output[idx_train], labels[idx_train])
        acc_train = accuracy(output[idx_train], labels[idx_train])
        loss_train.backward()
        optimizer.step()

        loss_val = F.nll_loss(output[idx_val], labels[idx_val])
        acc_val = accuracy(output[idx_val], labels[idx_val])
        print("Epoch: {:04d}".format(epoch+1),
              "loss_train: {:.4f}".format(loss_train.item()),
              "acc_train: {:.4f}".format(acc_train.item()),
              "loss_val: {:.4f}".format(loss_val.item()),
              "acc_val: {:.4f}".format(acc_val.item()))

        optimizer.step()


def test(model):
    model.eval()
    output = model(features, R)
    loss_test = F.nll_loss(output[idx_test], labels[idx_test])
    acc_test = accuracy(output[idx_test], labels[idx_test])
    print("Test set results:",
          "loss= {:.4f}".format(loss_test.item()),
          "accuracy= {:.4f}".format(acc_test.item()))


if __name__ == "__main__":
    start_time = time.time()
    train(model, args.epochs)
    print(f"Training completed, costs {time.time()-start_time} seconds.")

    test(model)
