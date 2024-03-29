import argparse
import os
import sys
from glob import glob

import numpy as np
import yaml
from matplotlib import pyplot as plt
from scipy.stats import pearsonr, spearmanr
from tqdm import tqdm
from typing import Dict, Iterable
import random

os.environ["OMP_NUM_THREADS"] = "1"  # export OMP_NUM_THREADS=1
os.environ["OPENBLAS_NUM_THREADS"] = "1"  # export OPENBLAS_NUM_THREADS=1
os.environ["MKL_NUM_THREADS"] = "1"  # export MKL_NUM_THREADS=1
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"  # export VECLIB_MAXIMUM_THREADS=1
os.environ["NUMEXPR_NUM_THREADS"] = "1"  # export NUMEXPR_NUM_THREADS=1

import_dir = '/'.join(os.path.realpath(__file__).split('/')[:-2])
sys.path.insert(0, import_dir + '/utils/')
sys.path.insert(0, import_dir + '/embedding_preparation')
from attribute_hashmap import AttributeHashmap
from information import approx_eigvals, exact_eigvals, \
    mutual_information_per_class_simple, mutual_information_per_class_random_sample, \
        von_neumann_entropy, shannon_entropy, mutual_information_wrt_Input_sample, comp_diffusion_embedding
from diffusion import compute_diffusion_matrix
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


def plot_figures(data_arrays: Dict[str, Iterable],
                 save_paths_fig: Dict[str, str]) -> None:

    plt.rcParams['font.family'] = 'serif'
    plt.rcParams['legend.fontsize'] = 20

    # Plot of Diffusion Entropy vs. epoch.
    fig_entropy = plt.figure(figsize=(20, 20))
    ax = fig_entropy.add_subplot(1, 1, 1)
    ax_secondary = ax.twinx()
    ax.spines[['right', 'top']].set_visible(False)
    ax_secondary.spines[['left', 'top']].set_visible(False)
    ln1 = ax.plot(data_arrays['epoch'], data_arrays['se'], c='grey')
    ax.scatter(data_arrays['epoch'], data_arrays['se'], c='grey', s=120)
    ln2 = ax_secondary.plot(data_arrays['epoch'],
                            data_arrays['vne'],
                            c='mediumblue')
    ax_secondary.scatter(data_arrays['epoch'],
                         data_arrays['vne'],
                         c='mediumblue',
                         s=120)
    lns = ln1 + ln2
    ax.legend(lns, ['Shannon entropy', 'spectral von Neumann entropy'])
    fig_entropy.supylabel('Diffusion Entropy', fontsize=40)
    fig_entropy.supxlabel('Epochs Trained', fontsize=40)
    ax.tick_params(axis='both', which='major', labelsize=30)
    ax_secondary.tick_params(axis='both', which='major', labelsize=30)
    fig_entropy.savefig(save_paths_fig['fig_entropy'])
    plt.close(fig=fig_entropy)

    # Plot of Diffusion Entropy vs. Val. Acc.
    fig_entropy_corr = plt.figure(figsize=(20, 20))
    ax = fig_entropy_corr.add_subplot(1, 1, 1)
    ax_secondary = ax.twinx()
    ax.spines[['right', 'top']].set_visible(False)
    ax_secondary.spines[['left', 'top']].set_visible(False)
    ln1 = ax.scatter(data_arrays['acc'],
                     data_arrays['se'],
                     c='grey',
                     alpha=0.5,
                     s=300)
    ln2 = ax_secondary.scatter(data_arrays['acc'],
                               data_arrays['vne'],
                               c='mediumblue',
                               alpha=0.5,
                               s=300)
    lns = [ln1] + [ln2]
    ax.legend(lns, ['Shannon entropy', 'spectral von Neumann entropy'])
    fig_entropy_corr.supylabel('Diffusion Entropy', fontsize=40)
    fig_entropy_corr.supxlabel('Downstream Classification Accuracy',
                               fontsize=40)
    ax.tick_params(axis='both', which='major', labelsize=30)
    ax_secondary.tick_params(axis='both', which='major', labelsize=30)
    # Display correlation.
    if len(data_arrays['acc']) > 1:
        fig_entropy_corr.suptitle(
            'VNE Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f)' %
            (pearsonr(data_arrays['acc'], data_arrays['vne'])[0],
             pearsonr(data_arrays['acc'], data_arrays['vne'])[1],
             spearmanr(data_arrays['acc'], data_arrays['vne'])[0],
             spearmanr(data_arrays['acc'], data_arrays['vne'])[1]),
            fontsize=40)
    fig_entropy_corr.savefig(save_paths_fig['fig_entropy_corr'])
    plt.close(fig=fig_entropy_corr)

    # Plot of Mutual Information vs. epoch.
    fig_mi = plt.figure(figsize=(20, 20))
    ax = fig_mi.add_subplot(1, 1, 1)
    ax.spines[['right', 'top']].set_visible(False)
    # MI wrt Output
    ax.plot(data_arrays['epoch'], data_arrays['mi_Y_simple'], c='grey')
    ax.plot(data_arrays['epoch'], data_arrays['mi_Y'], c='mediumblue')
    ax.plot(data_arrays['epoch'],
            data_arrays['mi_Y_shannon'],
            c='darkblue',
            linestyle='-.')
    # MI wrt Input
    ax.plot(data_arrays['epoch'], data_arrays['mi_X'], c='green')
    ax.plot(data_arrays['epoch'],
            data_arrays['mi_X_shannon'],
            c='darkgreen',
            linestyle='-.')
    ax.legend([
        'I(Z; Y) simple', 'I(Z; Y)', 'I(Z; Y) shannon', 'I(Z; X)',
        'I(Z; X) shannon'
    ],
              loc='upper left')
    fig_mi.supylabel('Mutual Information', fontsize=40)
    fig_mi.supxlabel('Epochs Trained', fontsize=40)
    ax.tick_params(axis='both', which='major', labelsize=30)
    fig_mi.savefig(save_paths_fig['fig_mi'])
    plt.close(fig=fig_mi)

    # Plot of Mutual Information vs. Val. Acc.
    fig_mi_corr = plt.figure(figsize=(20, 20))
    ax = fig_mi_corr.add_subplot(1, 1, 1)
    ax.spines[['right', 'top']].set_visible(False)
    ax.scatter(data_arrays['acc'],
               data_arrays['mi_Y_simple'],
               c='grey',
               alpha=0.5,
               s=300)
    ax.scatter(data_arrays['acc'],
               data_arrays['mi_Y'],
               c='mediumblue',
               alpha=0.5,
               s=300)
    ax.scatter(data_arrays['acc'],
               data_arrays['mi_Y_shannon'],
               c='darkblue',
               alpha=0.5,
               s=300,
               linewidths=5)
    ax.scatter(data_arrays['acc'],
               data_arrays['mi_X'],
               c='green',
               alpha=0.5,
               s=300,
               linewidths=5)
    ax.scatter(data_arrays['acc'],
               data_arrays['mi_X_shannon'],
               c='darkgreen',
               alpha=0.5,
               s=300,
               linewidths=5)
    ax.legend([
        'I(Z; Y) simple', 'I(Z; Y)', 'I(Z; Y) shannon', 'I(Z; X)',
        'I(Z; X) shannon'
    ],
              loc='upper left')
    fig_mi_corr.supylabel('Mutual Information', fontsize=40)
    fig_mi_corr.supxlabel('Downstream Classification Accuracy', fontsize=40)
    ax.tick_params(axis='both', which='major', labelsize=30)

    # # Display correlation.
    if len(data_arrays['acc']) > 1:
        fig_mi_corr.suptitle(
            'I(Z; Y) simple, Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f);\n'
            % (pearsonr(data_arrays['acc'], data_arrays['mi_Y_simple'])[0],
               pearsonr(data_arrays['acc'], data_arrays['mi_Y_simple'])[1],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y_simple'])[0],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y_simple'])[1]) +
            '\nI(Z; Y), Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f);\n'
            % (pearsonr(data_arrays['acc'], data_arrays['mi_Y'])[0],
               pearsonr(data_arrays['acc'], data_arrays['mi_Y'])[1],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y'])[0],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y'])[1]) +
            '\nI(Z; Y) shannon, Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f);\n'
            % (pearsonr(data_arrays['acc'], data_arrays['mi_Y_shannon'])[0],
               pearsonr(data_arrays['acc'], data_arrays['mi_Y_shannon'])[1],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y_shannon'])[0],
               spearmanr(data_arrays['acc'], data_arrays['mi_Y_shannon'])[1]) +
            '\nI(Z; X), Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f);\n'
            % (pearsonr(data_arrays['acc'], data_arrays['mi_X'])[0],
               pearsonr(data_arrays['acc'], data_arrays['mi_X'])[1],
               spearmanr(data_arrays['acc'], data_arrays['mi_X'])[0],
               spearmanr(data_arrays['acc'], data_arrays['mi_X'])[1]) +
            '\nI(Z; X) shannon, Pearson R: %.3f (p = %.4f), Spearman R: %.3f (p = %.4f);\n'
            % (pearsonr(data_arrays['acc'], data_arrays['mi_X_shannon'])[0],
               pearsonr(data_arrays['acc'], data_arrays['mi_X_shannon'])[1],
               spearmanr(data_arrays['acc'], data_arrays['mi_X_shannon'])[0],
               spearmanr(data_arrays['acc'], data_arrays['mi_X_shannon'])[1]),
            fontsize=30)
    fig_mi_corr.subplots_adjust(top=0.8)
    fig_mi_corr.savefig(save_paths_fig['fig_mi_corr'])
    plt.close(fig=fig_mi_corr)

    return


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',
                        help='Path to config yaml file.',
                        required=True)
    parser.add_argument('--t', type=int, default=2)
    parser.add_argument('--gaussian-kernel-sigma', type=float, default=10.0)
    parser.add_argument(
        '--chebyshev',
        action='store_true',
        help='Chebyshev approximation instead of full eigendecomposition.')
    parser.add_argument(
        '--random-seed',
        help='Only enter if you want to override the config!!!',
        type=int,
        default=None)
    args = vars(parser.parse_args())
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
        glob(
            '%s/embeddings/%s-%s-%s-seed%s%s-epoch*' %
            (config.output_save_path, config.dataset, method_str, config.model,
             config.random_seed, '-zeroinit' if config.zero_init else '')))

    save_root = './results_diffusion_entropy/'
    save_root_override = './results_diffusion_entropy_t=%d/' % args.t
    os.makedirs(save_root, exist_ok=True)

    save_paths_fig = {
        'fig_entropy':
        '%s/diffusion-entropy-%s-%s-%s-seed%s.png' %
        (save_root_override, config.dataset, method_str, config.model,
         config.random_seed),
        'fig_entropy_corr':
        '%s/diffusion-entropy-corr-%s-%s-%s-seed%s.png' %
        (save_root_override, config.dataset, method_str, config.model,
         config.random_seed),
        'fig_mi':
        '%s/class-mutual-information-%s-%s-%s-seed%s.png' %
        (save_root_override, config.dataset, method_str, config.model,
         config.random_seed),
        'fig_mi_corr':
        '%s/class-mutual-information-corr-%s-%s-%s-seed%s.png' %
        (save_root_override, config.dataset, method_str, config.model,
         config.random_seed)
    }

    save_path_final_npy = '%s/numpy_files/figure-data-%s-%s-%s-seed%s.npy' % (
        save_root_override, config.dataset, method_str, config.model,
        config.random_seed)

    log_path = '%s/log-%s-%s-%s-seed%s.txt' % (
        save_root_override, config.dataset, method_str, config.model,
        config.random_seed)

    os.makedirs(os.path.dirname(save_path_final_npy), exist_ok=True)
    if os.path.exists(save_path_final_npy):
        data_numpy = np.load(save_path_final_npy)
        data_arrays = {
            'epoch': data_numpy['epoch'],
            'acc': data_numpy['acc'],
            'se': data_numpy['se'],
            'vne': data_numpy['vne'],
            'mi_Y_simple': data_numpy['mi_Y_simple'],
            'mi_Y': data_numpy['mi_Y'],
            'H_ZgivenY': data_numpy['H_ZgivenY'],
            'mi_X': data_numpy['mi_X'],
            'mi_Y_shannon': data_numpy['mi_Y_shannon'],
            'mi_X_shannon': data_numpy['mi_X_shannon'],
        }
        plot_figures(data_arrays=data_arrays, save_paths_fig=save_paths_fig)

    else:
        epoch_list, acc_list, se_list, vne_list, \
            mi_Y_simple_list, mi_Y_append_list, mi_Y_list, H_ZgivenY_list, mi_X_list, mi_Y_shannon_list, mi_X_shannon_list \
                = [], [], [], [], [], [], [], [], [], [], []
        input_clusters = None

        for i, embedding_folder in enumerate(embedding_folders):
            epoch_list.append(
                int(embedding_folder.split('epoch')[-1].split('-valAcc')[0]) +
                1)
            acc_list.append(
                float(
                    embedding_folder.split('-valAcc')[1].split('-divergence')
                    [0]))

            files = sorted(glob(embedding_folder + '/*'))
            checkpoint_name = os.path.basename(embedding_folder)
            log(checkpoint_name, log_path)

            labels, embeddings, orig_input = None, None, None

            for file in tqdm(files):
                np_file = np.load(file)
                curr_input = np_file['image']
                curr_label = np_file['label_true']
                curr_embedding = np_file['embedding']

                if labels is None:
                    orig_input = curr_input
                    labels = curr_label[:, None]  # expand dim to [B, 1]
                    embeddings = curr_embedding
                else:
                    orig_input = np.vstack((orig_input, curr_input))
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
            '''Shannon Entropy of embeddings'''
            se = shannon_entropy(embeddings)
            se_list.append(se)
            log('Shannon Entropy = %.4f' % se, log_path)

            #
            '''Diffusion Matrix and Diffusion Eigenvalues'''
            save_path_eigenvalues = '%s/numpy_files/diffusion-eigenvalues/diffusion-eigenvalues-%s.npz' % (
                save_root, checkpoint_name)
            os.makedirs(os.path.dirname(save_path_eigenvalues), exist_ok=True)
            if os.path.exists(save_path_eigenvalues):
                data_numpy = np.load(save_path_eigenvalues)
                eigenvalues_P = data_numpy['eigenvalues_P']
                print('Pre-computed eigenvalues loaded.')
            else:
                diffusion_matrix = compute_diffusion_matrix(
                    embeddings, sigma=args.gaussian_kernel_sigma)
                print('Diffusion matrix computed.')

                if args.chebyshev:
                    eigenvalues_P = approx_eigvals(diffusion_matrix)
                else:
                    eigenvalues_P = exact_eigvals(diffusion_matrix)

                # Lower precision to save disk space.
                eigenvalues_P = eigenvalues_P.astype(np.float16)
                with open(save_path_eigenvalues, 'wb+') as f:
                    np.savez(f, eigenvalues_P=eigenvalues_P)
                print('Eigenvalues computed.')

            eig_thr_list = [0.5, 0.2, 0.1, 5e-2, 1e-2, 1e-3, 1e-4]
            log('# eigenvalues > thr: %s' % eig_thr_list, log_path)
            log(
                't = 1: ' +
                str([np.sum(eigenvalues_P > thr) for thr in eig_thr_list]),
                log_path)
            log(
                't = %d: ' % args.t + str([
                    np.sum(eigenvalues_P**args.t > thr) for thr in eig_thr_list
                ]), log_path)

            #
            '''Diffusion Entropy'''
            log('von Neumann Entropy: ', log_path)
            vne = von_neumann_entropy(eigenvalues_P, t=args.t)
            vne_list.append(vne)
            log('Diffusion Entropy = %.4f' % vne, log_path)

            #
            '''Mutual Information between z and Output Class'''
            log('Mutual Information between z and Output Class: ', log_path)

            mi_Y_simple, H_ZgivenY_map, H_ZgivenY = mutual_information_per_class_simple(
                embeddings=embeddings,
                labels=labels,
                H_Z=vne,
                sigma=args.gaussian_kernel_sigma,
                vne_t=args.t,
                chebyshev_approx=args.chebyshev)
            mi_Y_simple_list.append(mi_Y_simple)
            H_ZgivenY_list.append(H_ZgivenY)
            log('MI between z and Output (full graph) = %.4f' % mi_Y_simple,
                log_path)

            mi_Y, _, _ = mutual_information_per_class_random_sample(
                embeddings=embeddings,
                labels=labels,
                H_ZgivenY_map=H_ZgivenY_map,
                sigma=args.gaussian_kernel_sigma,
                vne_t=args.t,
                chebyshev_approx=args.chebyshev)
            mi_Y_list.append(mi_Y)
            log('MI between z and Output = %.4f' % mi_Y, log_path)

            mi_Y_shannon, _, _ = mutual_information_per_class_random_sample(
                embeddings=embeddings,
                labels=labels,
                H_ZgivenY_map=None,
                sigma=args.gaussian_kernel_sigma,
                vne_t=args.t,
                use_shannon_entropy=True,
                chebyshev_approx=args.chebyshev)
            mi_Y_shannon_list.append(mi_Y_shannon)
            log('MI between z and Output (Shannon) = %.4f' % mi_Y_shannon,
                log_path)

            #
            '''Mutual Information between z and Input'''
            orig_input = np.reshape(orig_input,
                                    (N, -1))  # [N, W, H, C] -> [N, W*H*C]

            mi_X, input_clusters = mutual_information_wrt_Input_sample(
                embeddings=embeddings,
                input=orig_input,
                input_clusters=input_clusters,
                sigma=args.gaussian_kernel_sigma,
                vne_t=args.t,
                chebyshev_approx=args.chebyshev)
            mi_X_list.append(mi_X)
            log('Mutual Information between z and Input = %.4f' % mi_X,
                log_path)

            mi_X_shannon, input_clusters = mutual_information_wrt_Input_sample(
                embeddings=embeddings,
                input=orig_input,
                input_clusters=input_clusters,
                sigma=args.gaussian_kernel_sigma,
                vne_t=args.t,
                use_shannon_entropy=True,
                chebyshev_approx=args.chebyshev)
            mi_X_shannon_list.append(mi_X_shannon)
            log(
                'Mutual Information between z and Input (Shannon) = %.4f' %
                mi_X_shannon, log_path)

            # Plotting
            data_arrays = {
                'epoch': epoch_list,
                'acc': acc_list,
                'se': se_list,
                'vne': vne_list,
                'mi_Y_simple': mi_Y_simple_list,
                'mi_Y': mi_Y_list,
                'H_ZgivenY': H_ZgivenY_list,
                'mi_X': mi_X_list,
                'mi_Y_shannon': mi_Y_shannon_list,
                'mi_X_shannon': mi_X_shannon_list,
            }
            plot_figures(data_arrays=data_arrays,
                         save_paths_fig=save_paths_fig)

        with open(save_path_final_npy, 'wb+') as f:
            np.savez(f,
                     epoch=np.array(epoch_list),
                     acc=np.array(acc_list),
                     se=np.array(se_list),
                     vne=np.array(vne_list),
                     mi_Y_simple=np.array(mi_Y_simple_list),
                     mi_Y=np.array(mi_Y_list),
                     H_ZgivenY=np.array(H_ZgivenY_list),
                     mi_X=np.array(mi_X_list),
                     mi_Y_shannon=np.array(mi_Y_shannon_list),
                     mi_X_shannon=np.array(mi_X_shannon_list))
