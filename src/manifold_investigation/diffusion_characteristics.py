import argparse
import os
import sys
from glob import glob

import numpy as np
import phate
import scprep
import seaborn as sns
import yaml
from matplotlib import pyplot as plt
from scipy import sparse
from sklearn.metrics import pairwise_distances
from tqdm import tqdm

os.environ["OMP_NUM_THREADS"] = "1"  # export OMP_NUM_THREADS=1
os.environ["OPENBLAS_NUM_THREADS"] = "1"  # export OPENBLAS_NUM_THREADS=1
os.environ["MKL_NUM_THREADS"] = "1"  # export MKL_NUM_THREADS=1
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"  # export VECLIB_MAXIMUM_THREADS=1
os.environ["NUMEXPR_NUM_THREADS"] = "1"  # export NUMEXPR_NUM_THREADS=1

import_dir = '/'.join(os.path.realpath(__file__).split('/')[:-2])
sys.path.insert(0, import_dir + '/utils/')
from attribute_hashmap import AttributeHashmap
from log_utils import log
from path_utils import update_config_dirs

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


def von_neumann_entropy(data, trivial_thr: float = 0.9):
    from scipy.linalg import svd
    _, eigenvalues, _ = svd(data)

    eigenvalues = np.array(sorted(eigenvalues)[::-1])
    # Drop the biggest eigenvalue(s).
    eigenvalues = eigenvalues[eigenvalues < trivial_thr]

    prob = eigenvalues / eigenvalues.sum()
    prob = prob + np.finfo(float).eps

    return -np.sum(prob * np.log(prob))


def get_laplacian_extrema(data,
                          n_extrema,
                          knn=10,
                          n_pca=100,
                          subsample=True,
                          random_state=0):
    '''
    Finds the 'Laplacian extrema' of a dataset.  The first extrema is chosen as
    the point that minimizes the first non-trivial eigenvalue of the Laplacian graph
    on the data.  Subsequent extrema are chosen by first finding the unique non-trivial
    non-negative vector that is zero on all previous extrema while at the same time
    minimizing the Laplacian quadratic form, then taking the argmax of this vector.
    '''
    import graphtools as gt
    import networkx as nx
    import scipy

    if subsample and data.shape[0] > 10000:
        np.random.seed(random_state)
        data = data[np.random.choice(data.shape[0], 10000, replace=False), :]
    G = gt.Graph(data, use_pygsp=True, decay=None, knn=knn, n_pca=n_pca)

    # We need to convert G into a NetworkX graph to use the Tracemin PCG algorithm
    G_nx = nx.convert_matrix.from_scipy_sparse_array(G.W)
    fiedler = nx.linalg.algebraicconnectivity.fiedler_vector(
        G_nx, method='tracemin_pcg')

    # Combinatorial Laplacian gives better results than the normalized Laplacian
    L = nx.laplacian_matrix(G_nx)
    first_extrema = np.argmax(fiedler)
    extrema = [first_extrema]
    extrema_ordered = [first_extrema]

    init_lanczos = fiedler
    init_lanczos = np.delete(init_lanczos, first_extrema)
    for i in range(n_extrema - 1):
        # Generate the Laplacian submatrix by removing rows/cols for previous extrema
        indices = range(data.shape[0])
        indices = np.delete(indices, extrema)
        ixgrid = np.ix_(indices, indices)
        L_sub = L[ixgrid]

        # Find the smallest eigenvector of our Laplacian submatrix
        eigvals, eigvecs = scipy.sparse.linalg.eigsh(L_sub,
                                                     k=1,
                                                     which='SM',
                                                     v0=init_lanczos)

        # Add it to the sorted and unsorted lists of extrema
        new_extrema = np.argmax(np.abs(eigvecs[:, 0]))
        init_lanczos = eigvecs[:, 0]
        init_lanczos = np.delete(init_lanczos, new_extrema)
        shift = np.searchsorted(extrema_ordered, new_extrema)
        extrema_ordered.insert(shift, new_extrema + shift)
        extrema.append(new_extrema + shift)

    return extrema


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        help='Path to config yaml file.',
                        required=True)
    parser.add_argument('-P',
                        '--plot-diffusion-eigenvalues',
                        help='Plot diffusion eigenvalues distribution.',
                        action='store_true')
    parser.add_argument('--knn', help='k for knn graph.', type=int, default=10)
    args = vars(parser.parse_args())
    args = AttributeHashmap(args)

    args = AttributeHashmap(args)
    config = AttributeHashmap(yaml.safe_load(open(args.config)))
    config = update_config_dirs(AttributeHashmap(config))

    embedding_folders = sorted(
        glob('%s/embeddings/%s-%s-*' %
             (config.output_save_path, config.dataset, config.contrastive)))

    save_root = './diffusion_PHATE/'
    os.makedirs(save_root, exist_ok=True)
    save_path_fig0 = '%s/diffusion-eigenvalues-%s-%s-knn-%s.png' % (
        save_root, config.dataset, config.contrastive, args.knn)
    save_path_fig1 = '%s/extrema-PHATE-%s-%s-knn-%s.png' % (
        save_root, config.dataset, config.contrastive, args.knn)
    save_path_fig2 = '%s/extrema-dist-PHATE-%s-%s-knn-%s.png' % (
        save_root, config.dataset, config.contrastive, args.knn)
    save_path_fig3 = '%s/von-Neumann-%s-%s-knn-%s.png' % (
        save_root, config.dataset, config.contrastive, args.knn)
    log_path = '%s/log-%s-%s-knn-%s.txt' % (save_root, config.dataset,
                                            config.contrastive, args.knn)

    num_rows = len(embedding_folders)
    fig0 = plt.figure(figsize=(8, 6 * num_rows))
    fig1 = plt.figure(figsize=(8, 5 * num_rows))
    fig2 = plt.figure(figsize=(8, 5 * num_rows))
    fig3 = plt.figure(figsize=(8, 5))
    von_neumann_thr_list = [0.5, 0.7, 0.9, 0.95, 0.99]
    vne_stats = {}
    vne_x_axis_text, vne_x_axis_value = [], []

    for i, embedding_folder in enumerate(embedding_folders):
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

        N, D = embeddings.shape

        assert labels.shape[0] == N
        assert labels.shape[1] == 1

        if config.dataset == 'cifar10':
            labels_updated = np.zeros(labels.shape, dtype='object')
            for k in range(N):
                labels_updated[k] = cifar10_int2name[labels[k].item()]
            labels = labels_updated
            del labels_updated

        # PHATE dimensionality reduction.
        phate_op = phate.PHATE(random_state=0,
                               n_jobs=1,
                               n_components=2,
                               knn=args.knn,
                               verbose=False)
        data_phate = phate_op.fit_transform(embeddings)

        #
        '''von Neumann Entropy'''
        # t = phate_op._find_optimal_t(t_max=100, plot=False, ax=None)
        # vne_ref = phate_op._von_neumann_entropy(t_max=t)[1][0]
        log('von Neumann Entropy: ', log_path)
        for trivial_thr in von_neumann_thr_list:
            vne = von_neumann_entropy(phate_op.diff_op,
                                      trivial_thr=trivial_thr)
            log(
                '    removing eigenvalues > %.2f: entropy = %.4f' %
                (trivial_thr, vne), log_path)

            if trivial_thr not in vne_stats.keys():
                vne_stats[trivial_thr] = [vne]
            else:
                vne_stats[trivial_thr].append(vne)

        vne_x_axis_text.append(checkpoint_name.split('_')[-1])
        if '%' in vne_x_axis_text[-1]:
            vne_x_axis_value.append(
                int(vne_x_axis_text[-1].split('%')[0]) / 100)
        else:
            vne_x_axis_value.append(vne_x_axis_value[-1] + 0.1)

        #
        '''Diffusion map'''
        if args.plot_diffusion_eigenvalues:
            save_path_eigenvalues = '%s/numpy_files/diffusion-eigenvalues-%s-%s-knn-%s-%s.npz' % (
                save_root, config.dataset, config.contrastive, args.knn,
                checkpoint_name.split('_')[-1])
            os.makedirs(os.path.dirname(save_path_eigenvalues), exist_ok=True)
            if os.path.exists(save_path_eigenvalues):
                # Load the eigenvalues if exists.
                data_numpy = np.load(save_path_eigenvalues)
                eigenvalues = data_numpy['eigenvalues']
            else:
                P = phate_op.graph.diff_op  # SPARSE instead of DENSE
                eigenvalues, _ = np.linalg.eig(P.toarray())
                # eigenvalues, eigenvectors = sparse.linalg.eigs(P, k=100)
                with open(save_path_eigenvalues, 'wb+') as f:
                    np.savez(f, eigenvalues=eigenvalues)
            ax0 = fig0.add_subplot(2 * num_rows, 1, 2 * i + 1)
            ax0.set_title(checkpoint_name)
            ax0.hist(eigenvalues, color='w', edgecolor='k')
            ax0 = fig0.add_subplot(2 * num_rows, 1, 2 * i + 2)
            sns.boxplot(x=eigenvalues, color='skyblue', ax=ax0)
            fig0.tight_layout()
            fig0.savefig(save_path_fig0)

        #
        '''Laplacian Extrema'''
        n_extrema = 10
        extrema_inds = get_laplacian_extrema(data=embeddings,
                                             n_extrema=n_extrema,
                                             knn=args.knn)

        ax = fig1.add_subplot(num_rows, 1, i + 1)
        colors = np.empty((N), dtype=object)
        colors.fill('Embedding\nVectors')
        colors[extrema_inds] = 'Laplacian\nExtrema'
        cmap = {
            'Embedding\nVectors': 'gray',
            'Laplacian\nExtrema': 'firebrick'
        }
        sizes = np.empty((N), dtype=int)
        sizes.fill(1)
        sizes[extrema_inds] = 50

        scprep.plot.scatter2d(data_phate,
                              c=colors,
                              cmap=cmap,
                              title='%s' % checkpoint_name,
                              legend_anchor=(1.25, 1),
                              ax=ax,
                              xticks=False,
                              yticks=False,
                              label_prefix='PHATE',
                              fontsize=8,
                              s=sizes)

        fig1.tight_layout()
        fig1.savefig(save_path_fig1)

        extrema = embeddings[extrema_inds]
        dist_matrix = pairwise_distances(extrema)
        distances = np.array([
            dist_matrix[i, j] for i in range(len(dist_matrix) - 1)
            for j in range(i + 1, len(dist_matrix))
        ])
        dist_mean = distances.mean()
        dist_std = distances.std()

        ax = fig2.add_subplot(num_rows, 1, i + 1)
        sns.heatmap(dist_matrix, ax=ax)
        ax.set_title('%s  Extrema Euc distance: %.2f \u00B1 %.2f' %
                     (checkpoint_name, dist_mean, dist_std))
        log('Extrema Euc distance: %.2f \u00B1 %.2f\n' % (dist_mean, dist_std),
            log_path)

        fig2.tight_layout()
        fig2.savefig(save_path_fig2)

    ax = fig3.add_subplot(1, 1, 1)
    for trivial_thr in von_neumann_thr_list:
        ax.scatter(vne_x_axis_value, vne_stats[trivial_thr])
    ax.legend(von_neumann_thr_list, bbox_to_anchor=(1.12, 0.4))
    ax.set_xticks(vne_x_axis_value)
    ax.set_xticklabels(vne_x_axis_text)
    ax.set_title(
        'von Neumann Entropy (at different eigenvalue removal threshold)')
    ax.spines[['right', 'top']].set_visible(False)
    # Plot separately to avoid legend mismatch.
    for trivial_thr in von_neumann_thr_list:
        ax.plot(vne_x_axis_value, vne_stats[trivial_thr])
    fig3.tight_layout()
    fig3.savefig(save_path_fig3)
