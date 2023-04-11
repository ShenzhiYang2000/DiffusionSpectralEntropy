import argparse
import os
import sys
from glob import glob
from typing import List

import numpy as np
import yaml
from matplotlib import pyplot as plt
from scipy.stats import pearsonr, spearmanr
from tqdm import tqdm

os.environ["OMP_NUM_THREADS"] = "1"  # export OMP_NUM_THREADS=1
os.environ["OPENBLAS_NUM_THREADS"] = "1"  # export OPENBLAS_NUM_THREADS=1
os.environ["MKL_NUM_THREADS"] = "1"  # export MKL_NUM_THREADS=1
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"  # export VECLIB_MAXIMUM_THREADS=1
os.environ["NUMEXPR_NUM_THREADS"] = "1"  # export NUMEXPR_NUM_THREADS=1

import_dir = '/'.join(os.path.realpath(__file__).split('/')[:-2])
sys.path.insert(0, import_dir + '/utils/')
from attribute_hashmap import AttributeHashmap
from diffusion import DiffusionMatrix
from log_utils import log
from path_utils import update_config_dirs
from seed import seed_everything

cifar10_int2name = {
    0: 'airplane',
    1: 'automobile',
    2: 'bird',
    3: 'cat',
    4: 'deer',
    5: 'dog',
    6: 'frog',
    7: 'horse',
    8: 'ship',
    9: 'truck',
}


def mutual_information(eigs: np.array,
                       eigs_by_class: List[np.array],
                       n_by_class: List[int],
                       eps: float = 1e-3):
    return NotImplementedError


def von_neumann_entropy(eigs: np.array, eps: float = 1e-3):
    eigenvalues = eigs.copy()

    eigenvalues = np.array(sorted(eigenvalues)[::-1])

    # Drop the trivial eigenvalue(s).
    eigenvalues = eigenvalues[eigenvalues <= 1 - eps]

    # Shift the negative eigenvalue(s) that occurred due to rounding errors.
    if eigenvalues.min() < 0:
        eigenvalues -= eigenvalues.min()

    # Remove the close-to-zero eigenvalue(s).
    eigenvalues = eigenvalues[eigenvalues >= eps]

    prob = eigenvalues / eigenvalues.sum()
    prob = prob + np.finfo(float).eps

    return -np.sum(prob * np.log(prob))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        help='Path to config yaml file.',
                        required=True)
    parser.add_argument('--knn', help='k for knn graph.', type=int, default=10)
    parser.add_argument(
        '--random_seed',
        help='Only enter if you want to override the config!!!',
        type=int,
        default=None)
    args = vars(parser.parse_args())
    args = AttributeHashmap(args)

    args = AttributeHashmap(args)
    config = AttributeHashmap(yaml.safe_load(open(args.config)))
    config = update_config_dirs(AttributeHashmap(config))
    if args.random_seed is not None:
        config.random_seed = args.random_seed

    seed_everything(config.random_seed)

    if 'contrastive' in config.keys():
        method_str = config.contrastive
    elif 'bad_method' in config.keys():
        method_str = config.bad_method

    # NOTE: Take all the checkpoints for all epochs. Ignore the fixed percentage checkpoints.
    embedding_folders = sorted(
        glob('%s/embeddings/%s-%s-%s-seed%s-epoch*' %
             (config.output_save_path, config.dataset, method_str,
              config.model, config.random_seed)))

    save_root = './results_diffusion_entropy/'
    os.makedirs(save_root, exist_ok=True)
    save_path_fig_vne = '%s/diffusion-entropy-%s-%s-%s-seed%s-knn%s.png' % (
        save_root, config.dataset, method_str, config.model,
        config.random_seed, args.knn)
    save_path_fig_vne_corr = '%s/diffusion-entropy-corr-%s-%s-%s-seed%s-knn%s.png' % (
        save_root, config.dataset, method_str, config.model,
        config.random_seed, args.knn)
    log_path = '%s/log-%s-%s-%s-seed%s-knn%s.txt' % (
        save_root, config.dataset, method_str, config.model,
        config.random_seed, args.knn)

    num_rows = len(embedding_folders)
    epoch_list, acc_list, vne_list = [], [], []

    for i, embedding_folder in enumerate(embedding_folders):
        epoch_list.append(
            int(embedding_folder.split('epoch')[-1].split('-valAcc')[0]) + 1)
        acc_list.append(float(embedding_folder.split('-valAcc')[1]))

        files = sorted(glob(embedding_folder + '/*'))
        checkpoint_name = os.path.basename(embedding_folder)
        log(checkpoint_name, log_path)

        labels, embeddings = None, None

        for file in tqdm(files):
            np_file = np.load(file)
            curr_label = np_file['label_true']
            curr_embedding = np_file['embedding']

            if labels is None:
                labels = curr_label[:, None]  # expand dim to [B, 1]
                embeddings = curr_embedding
            else:
                labels = np.vstack((labels, curr_label[:, None]))
                embeddings = np.vstack((embeddings, curr_embedding))

        # This is the matrix of N embedding vectors each at dim [1, D].
        N, D = embeddings.shape

        assert labels.shape[0] == N
        assert labels.shape[1] == 1

        if config.dataset == 'cifar10':
            labels_updated = np.zeros(labels.shape, dtype='object')
            for k in range(N):
                labels_updated[k] = cifar10_int2name[labels[k].item()]
            labels = labels_updated
            del labels_updated

        #
        '''Diffusion Matrix'''
        save_path_diffusion = '%s/numpy_files/diffusion/diffusion-%s.npz' % (
            save_root, checkpoint_name)
        os.makedirs(os.path.dirname(save_path_diffusion), exist_ok=True)
        if os.path.exists(save_path_diffusion):
            data_numpy = np.load(save_path_diffusion)
            diffusion_matrix = data_numpy['diffusion_matrix']
            print('Pre-computed diffusion matrix loaded.')
        else:
            diffusion_matrix = DiffusionMatrix(embeddings, k=args.knn)
            with open(save_path_diffusion, 'wb+') as f:
                np.savez(f, diffusion_matrix=diffusion_matrix)
            print('Diffusion matrix computed.')

        #
        '''Diffusion Eigenvalues'''
        save_path_eigenvalues = '%s/numpy_files/diffusion-eigenvalues/diffusion-eigenvalues-%s.npz' % (
            save_root, checkpoint_name)
        os.makedirs(os.path.dirname(save_path_eigenvalues), exist_ok=True)
        if os.path.exists(save_path_eigenvalues):
            data_numpy = np.load(save_path_eigenvalues)
            eigenvalues_P = data_numpy['eigenvalues_P']
            print('Pre-computed eigenvalues loaded.')
        else:
            eigenvalues_P = np.linalg.eigvals(diffusion_matrix)
            with open(save_path_eigenvalues, 'wb+') as f:
                np.savez(f, eigenvalues_P=eigenvalues_P)
            print('Eigenvalues computed.')

        #
        '''Diffusion Entropy'''
        log('von Neumann Entropy (diffcur adaptive anisotropic P matrix): ',
            log_path)
        vne = von_neumann_entropy(eigenvalues_P)
        vne_list.append(vne)
        log('Diffusion Entropy = %.4f' % vne, log_path)

        #
        '''Plotting'''
        plt.rcParams['font.family'] = 'serif'

        # Plot of Diffusion Entropy vs. epoch.
        fig_vne = plt.figure(figsize=(20, 20))
        ax = fig_vne.add_subplot(1, 1, 1)
        ax.spines[['right', 'top']].set_visible(False)
        ax.scatter(epoch_list, vne_list, c='mediumblue', s=120)
        ax.plot(epoch_list, vne_list, c='mediumblue')
        fig_vne.supylabel('Diffusion Entropy', fontsize=40)
        fig_vne.supxlabel('Epochs Trained', fontsize=40)
        ax.tick_params(axis='both', which='major', labelsize=30)
        fig_vne.savefig(save_path_fig_vne)
        plt.close(fig=fig_vne)

        # Plot of Diffusion Entropy vs. Val. Acc.
        fig_vne_corr = plt.figure(figsize=(20, 20))
        ax = fig_vne_corr.add_subplot(1, 1, 1)
        ax.spines[['right', 'top']].set_visible(False)
        ax.scatter(acc_list,
                   vne_list,
                   facecolors='none',
                   edgecolors='mediumblue',
                   s=500,
                   linewidths=5)
        fig_vne_corr.supylabel('Diffusion Entropy', fontsize=40)
        fig_vne_corr.supxlabel('Downstream Classification Accuracy',
                               fontsize=40)
        ax.tick_params(axis='both', which='major', labelsize=30)
        # Display correlation.
        if len(acc_list) > 1:
            fig_vne_corr.suptitle(
                'Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f)' %
                (pearsonr(acc_list, vne_list)[0], pearsonr(
                    acc_list, vne_list)[1], spearmanr(acc_list, vne_list)[0],
                 spearmanr(acc_list, vne_list)[1]),
                fontsize=40)
        fig_vne_corr.savefig(save_path_fig_vne_corr)
        plt.close(fig=fig_vne_corr)
