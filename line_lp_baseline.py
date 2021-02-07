import logging
import os
import random
import time
from argparse import ArgumentParser

import networkx as nx
import numpy as np
import scipy.sparse as ssp
import torch
from models.line import run_LINE

from utils import accuracy, f1, normalize, to_torch, aug_normalized_adjacency
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import KFold
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.preprocessing import normalize

logger = logging.getLogger('line_baseline')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s %(filename)s %(lineno)d %(levelname)s: %(message)s')

parser = ArgumentParser()
parser.add_argument("--dataset", type=str, help="Dataset name")
parser.add_argument("--seed", type=int, default=42, help="RNG seed")
parser.add_argument('--epochs', type=int, default=100, help='Number of epochs')

args = parser.parse_args()
if len(logger.handlers) < 2:
    filename = f'line_baseline_{args.dataset}.log'
    file_handler = logging.FileHandler(filename, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
logger.debug(args)

np.random.seed(args.seed)
torch.manual_seed(args.seed)
torch.cuda.manual_seed(args.seed)

def learn_embeds():
    adj = ssp.load_npz(os.path.join('/data', args.dataset, 'adj.npz'))
    G = nx.from_scipy_sparse_matrix(adj, edge_attribute='weight', create_using=nx.Graph())
    start_time = time.perf_counter()
    embeds = run_LINE(G, args.epochs)
    end_time = time.perf_counter()
    logger.info(f"LINE learning costs {end_time-start_time:.4f} seconds")

    if not os.path.exists(f'output/{args.dataset}'):
        os.mkdir(f'output/{args.dataset}')
    np.save(os.path.join('output', args.dataset, 'line.npy'), embeds)
    return embeds

def load_embeds():
    tmp_embeds = np.genfromtxt(f'/data/{args.dataset}/vec_all.txt', skip_header=1)
    embeds = np.zeros((tmp_embeds.shape[0], tmp_embeds.shape[1]-1))
    for i in range(tmp_embeds.shape[0]):
        idx = int(tmp_embeds[i, 0])
        embeds[i] = tmp_embeds[i, 1:]
    return embeds


def test(dataset, embeds):
    positive = np.load(f'/data/{args.dataset}/positive.npy').astype(np.int)
    negative = np.load(f'/data/{args.dataset}/negative.npy').astype(np.int)
    pos_embeds = []
    neg_embeds = []
    pos_labels = np.array([1] * len(positive))
    neg_labels = np.array([0] * len(negative))
    for i, j in positive:
        pos_embeds.append(np.multiply(embeds[i], embeds[j]))
    for i, j in negative:
        neg_embeds.append(np.multiply(embeds[i], embeds[j]))
    pos_embeds, neg_embeds = np.array(pos_embeds), np.array(neg_embeds)
    X = np.concatenate([pos_embeds, neg_embeds])
    y = np.concatenate([pos_labels, neg_labels])

    kfold = KFold(n_splits=5, shuffle=True, random_state=42)
    scores = 0.0
    for train_id, test_id in kfold.split(X):
        logit = LogisticRegression(random_state=42)
        logit.fit(X[train_id], y[train_id])
        probs = logit.predict_proba(X[test_id])[:, 1]
        auc_score = roc_auc_score(y[test_id], probs)
        scores += auc_score
        logger.debug(f'auc score: {auc_score}')
    logger.info(f'Average auc score: {scores / 5}')

if __name__ == "__main__":
    embeds = learn_embeds()
    test(args.dataset, embeds)
