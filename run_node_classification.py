import logging
import os
import time
from argparse import ArgumentParser

import networkx as nx
import numpy as np
import scipy.sparse as ssp
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score

from models.deepwalk import deepwalk
from models.line import run_LINE
from utils import accuracy, f1, load_dataset, aug_normalized_adjacency, to_torch

logger = logging.getLogger('node_classification')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s %(filename)s %(lineno)d %(levelname)s: %(message)s')

parser = ArgumentParser()
parser.add_argument('--dataset', type=str)
parser.add_argument('--method', type=str, choices=['deepwalk', 'line'], help='Embed method')
parser.add_argument('--power', type=int, default=8, help='Maximum Power of smooth filter')
parser.add_argument('--epochs', type=int, default=100, help='Number of epochs (only for LINE)')
parser.add_argument('--embed_path', type=str, default='', help='Pre-trained embedding path')
args = parser.parse_args()

if len(logger.handlers) < 2:
    filename = f'nc_{args.method}_{args.dataset}.log'
    file_handler = logging.FileHandler(filename, mode='a')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
logger.debug(args)


def learn_embeds_dw():
    adj = ssp.load_npz(os.path.join('data', args.dataset, 'A_s.npz')).tocsr()
    G = nx.from_scipy_sparse_matrix(adj, edge_attribute='weight', create_using=nx.Graph())
    G.remove_edges_from(nx.selfloop_edges(G))
    del adj
    logger.info("Start training DeepWalk...")
    start_time = time.perf_counter()
    embeds = deepwalk(G)
    end_time = time.perf_counter()
    logger.info(f"Deepwalk learning costs {end_time-start_time:.4f} seconds")

    if not os.path.exists(f'output/{args.dataset}'):
        os.mkdir(f'output/{args.dataset}')
    # np.save(os.path.join('output', args.dataset, 'deepwalk.npy'), embeds)
    return embeds, end_time - start_time


def learn_embeds_line():
    adj = ssp.load_npz(os.path.join('data', args.dataset, 'A_s.npz')).tocsr()
    G = nx.from_scipy_sparse_matrix(adj, edge_attribute='weight', create_using=nx.Graph())
    del adj
    logger.info("Start training LINE...")
    start_time = time.process_time()
    embeds = run_LINE(G, args.epochs, 5)
    end_time = time.process_time()
    logger.info(f"LINE learning costs {end_time-start_time:.4f} seconds")

    if not os.path.exists(f'output/{args.dataset}'):
        os.mkdir(f'output/{args.dataset}')
    np.save(os.path.join('output', args.dataset, 'line.npy'), embeds)
    return embeds, end_time - start_time


def load_embeds_line():
    tmp_embeds = np.genfromtxt(f'data/{args.dataset}/vec_all.txt', skip_header=1)
    embeds = np.zeros((tmp_embeds.shape[0], tmp_embeds.shape[1]-1))
    for i in range(tmp_embeds.shape[0]):
        idx = int(tmp_embeds[i, 0])
        embeds[i] = tmp_embeds[i, 1:]
    return embeds


def test_node_classification(dataset, embeds, power):
    # adj, adj_s, features, labels, full_labels, indices, full_indices = load_dataset(dataset)
    adj = ssp.load_npz('/data/citeseer/adj.npz')
    filter = aug_normalized_adjacency(adj)
    # del adj_s, features, labels, indices
    R = ssp.load_npz(f'/data/{args.dataset}/R.npz')

    start_time = time.process_time()
    embeds = R @ embeds
    for _ in range(power):
        embeds = filter @ embeds
    end_time = time.process_time()
    logger.info(f'Refinement costs {end_time-start_time:.4f} seconds')
    
    full_indices = np.load('/data/citeseer/indices.npz')
    full_labels = np.load('/data/citeseer/labels.npy')
    train_idx, val_idx, test_idx = full_indices['train'], full_indices['val'], full_indices['test']
    print(len(full_labels))

    print(embeds.shape, full_labels.shape)
    model = LogisticRegression(solver='lbfgs', multi_class='auto')
    model.fit(embeds[train_idx], full_labels[train_idx])
    predict = model.predict(embeds[test_idx])
    acc_test = accuracy_score(full_labels[test_idx], predict)
    logger.info(f'Test set results: accuracy= {acc_test:.4f}')

    return end_time - start_time

if __name__ == '__main__':
    embeds = None
    embed_time = 0.0
    if len(args.embed_path) > 0:
        embeds = np.load(args.embed_path)
    elif args.method == 'deepwalk':
        embeds, embed_time = learn_embeds_dw()
    elif args.method == 'line':
        embeds, embed_time = learn_embeds_line()
        # embeds = load_embeds_line()
    else:
        raise NotImplementedError(f'Unsupported method: {args.method}')
    
    for p in range(args.power):
        refinement_time = test_node_classification(args.dataset, embeds, p)
        logger.info(f'Total time: {embed_time + refinement_time:.4f} seconds')
