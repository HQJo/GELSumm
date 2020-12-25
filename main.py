import logging
import os
import pickle
import time
from argparse import ArgumentParser

import numpy as np
import scipy.sparse as ssp
import torch
import torch.nn.functional as F
import torch.optim as optim

from summGCN import SummGCN
from utils import accuracy, load_data, normalize, to_torch

logger = logging.getLogger('summGCN')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s %(filename)s %(lineno)d %(levelname)s: %(message)s')

time_str = time.strftime('%Y-%m-%d-%H-%M')
if len(logger.handlers) < 2:
    filename = f'summGCN_{time_str}.log'
    file_handler = logging.FileHandler(filename, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

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
parser.add_argument("--type", type=str, choices=["rw", "symm"], default="rw",
                    help="Aggregation type")
parser.add_argument("--log_turn", type=int, default=10,
                    help="Number of turn to log")
args = parser.parse_args()
logger.debug("Args:")
logger.debug(args)

gpu_id = args.cuda
if not torch.cuda.is_available():
    gpu_id = -1
np.random.seed(args.seed)
torch.manual_seed(args.seed)

R, S, A, A_s, features, labels, idx_train, idx_val, idx_test = load_data(
    args.dataset)
N, d = features.shape
n = S.shape[1]
nclass = labels.max().item() + 1
logger.info(f"Dataset loaded. N: {N}, n: {n}, feature: {d}-dim")
logger.info(
    f"Train: {len(idx_train)}, Val: {len(idx_val)}, Test: {len(idx_test)}")

# features = normalize(features)
features_s = S.T @ features
if args.type == "rw":
    adj = normalize(A_s)
else:
    adj = R @ A_s @ R
    # adj = (S.T @ S) @ adj
A += ssp.eye(N)
degs = np.array(A.sum(axis=1)).squeeze()
D_inv = ssp.diags(np.power(np.sqrt(degs), -1))
A = D_inv @ A @ D_inv

S, A, adj, features_s, labels = to_torch(S), to_torch(A), to_torch(
    adj), to_torch(features_s), to_torch(labels)
idx_train, idx_val, idx_test = to_torch(
    idx_train), to_torch(idx_val), to_torch(idx_test)

device = f"cuda:{gpu_id}"
if gpu_id >= 0:
    A = A.cuda(device)
    adj = adj.cuda(device)
    S = S.cuda(device)
    features_s = features_s.cuda(device)
    labels = labels.cuda(device)
    idx_train = idx_train.cuda(device)
    idx_val = idx_val.cuda(device)
    idx_test = idx_test.cuda(device)

model = SummGCN(d, args.hidden, nclass, S, dropout=args.dropout)
if gpu_id >= 0:
    model = model.cuda(device)


def train(model, epochs):
    max_val_acc = 0.0
    best_params = None
    optimizer = optim.Adam(model.parameters(),
                           lr=args.lr, weight_decay=args.weight_decay)
    for epoch in range(epochs):
        start = time.time()
        model.train()
        optimizer.zero_grad()
        embeds = model((features_s, adj))
        # embeds = torch.spmm(A, embeds)
        output = F.log_softmax(embeds, dim=1)

        y_, y = output[idx_train], labels[idx_train]
        loss_train = F.nll_loss(y_, y)
        acc_train = accuracy(output[idx_train], labels[idx_train])
        loss_train.backward()
        optimizer.step()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5)

        model.eval()
        embeds = model((features_s, adj))
        # embeds = torch.spmm(A, embeds)
        output = F.log_softmax(embeds, dim=1)
        y_, y = output[idx_val], labels[idx_val]
        loss_val = F.nll_loss(y_, y)
        acc_val = accuracy(y_, y)
        if acc_val.cpu().item() > max_val_acc:
            max_val_acc = acc_val.cpu().item()
            best_params = model.state_dict()
        end = time.time()

        message = "{} {} {} {} {} {}".format(
            "Epoch: {:04d}".format(epoch+1),
            "loss_train: {:.4f}".format(loss_train.cpu().item()),
            "acc_train: {:.4f}".format(acc_train.cpu().item()),
            "loss_val: {:.4f}".format(loss_val.cpu().item()),
            "acc_val: {:.4f}".format(acc_val.cpu().item()),
            "time: {:.2f} s".format(end - start)
        )
        if args.log_turn <= 0:
            logger.debug(message)
        elif epoch % args.log_turn == args.log_turn - 1:
            logger.info(message)
        else:
            logger.debug(message)

        optimizer.step()
    model.load_state_dict(best_params)


def test(model):
    model.eval()
    embeds = model((features_s, adj))
    output = F.log_softmax(embeds, dim=1)
    loss_test = F.nll_loss(output[idx_test], labels[idx_test])
    acc_test = accuracy(output[idx_test], labels[idx_test])
    message = f"Test set results: loss= {loss_test.item():.4f} accuracy= {acc_test.item():.4f}"
    logger.info(message)


if __name__ == "__main__":
    logger.info("Start training...")
    start_time = time.time()
    train(model, args.epochs)
    logger.info(f"Training completed, costs {time.time()-start_time} seconds.")

    test(model)
    if not os.path.exists(os.path.join('output', args.dataset)):
        os.makedirs(os.path.join('output', args.dataset))
    pickle.dump(model.state_dict(), open(os.path.join(
        'output', args.dataset, f'model_{time_str}.pkl'), 'wb'))
