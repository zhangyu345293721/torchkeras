import pandas as pd
from tqdm import tqdm
import torch
from .utils import printlog, prettydf

def merge_state(state_list, weights=None):
    """
    Merges states from multiple checkpoints with optional weights.

    Args:
        state_list (list): List of checkpoint paths or state dictionaries.
        weights (list): List of weights corresponding to each state. If None, equal weights are assigned.

    Returns:
        dict: Merged state dictionary.
    """
    if weights is None:
        weights = [1 for _ in state_list]
    total = sum(weights)
    weights = [x / total for x in weights]

    if isinstance(state_list[0], str):
        state = {k: v * weights[0] for k, v in torch.load(state_list[0]).items()}
    else:
        state = {k: v * weights[0] for k, v in state_list[0].items()}

    for st, w in zip(state_list[1:], weights[1:]):
        if isinstance(st, str):
            st = torch.load(st)
        for k, v in st.items():
            state[k] = state[k] + w * v

    return state

def uniform_soup(model, ckpt_path_list, saved_ckpt_path='checkpoint_uniform_soup.pt'):
    """
    Uniformly merges states from multiple checkpoints and evaluates the model.

    Args:
        model: The PyTorch model.
        ckpt_path_list (list): List of checkpoint paths.
        saved_ckpt_path (str): Path to save the merged checkpoint.

    Returns:
        float: Evaluation score.
    """
    state = merge_state(ckpt_path_list)
    model.net.load_state_dict(state)
    score = model.evaluate(model.val_data, quiet=True)[model.monitor]
    torch.save(model.net.state_dict(), saved_ckpt_path)
    return score

def greedy_soup(model, ckpt_path_list, num_models=120, num_warmup=0, saved_ckpt_path='checkpoint_greedy_soup.pt'):
    """
    Greedily merges states from multiple checkpoints and evaluates the model.

    Args:
        model: The PyTorch model.
        ckpt_path_list (list): List of checkpoint paths.
        num_models (int): Number of models to merge.
        num_warmup (int): Number of warmup models (do not choose greedily).
        saved_ckpt_path (str): Path to save the merged checkpoint.

    Returns:
        float: Evaluation score.
    """
    dfckpt = pd.DataFrame({'ckpt_path': ckpt_path_list})

    scores = []
    printlog('step1: sort ckpt_path by metric...')

    loop = tqdm(dfckpt['ckpt_path'])
    for ckpt_path in loop:
        model.load_ckpt(ckpt_path)
        score = model.evaluate(model.val_data, quiet=True)[model.monitor]
        scores.append(score)
        loop.set_postfix(**{model.monitor: score})

    dfckpt['score'] = score


def optuna_soup(model,
                 ckpt_path_list,
                 n_trials=50,
                 timeout=1200,
                 saved_ckpt_path='checkpoint_optuna_soup.pt',
                 plot=True):
    """
    Perform an Optuna search to find optimal weights for checkpoint ensemble.

    Args:
        model: The PyTorch model.
        ckpt_path_list (list): List of checkpoint paths.
        n_trials (int): Number of optimization trials.
        timeout (int): Timeout for the optimization in seconds.
        saved_ckpt_path (str): Path to save the final checkpoint.
        plot (bool): Whether to plot the optimization analysis.

    Returns:
        float: Best evaluation score.
    """
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        weights_dict = {name: trial.suggest_int(name, 1, 100) for name in ckpt_path_list}
        state = merge_state(ckpt_path_list, weights=[weights_dict[name] for name in ckpt_path_list])
        model.net.load_state_dict(state)
        score = model.evaluate(model.val_data, quiet=True)[model.monitor]
        print(score)
        return score

    study = optuna.create_study(
        direction="maximize" if model.mode == 'max' else "minimize",
        study_name="optuna_ensemble"
    )

    printlog('step1: start Optuna search...')
    study.optimize(objective, n_trials=n_trials, timeout=timeout)

    printlog('step2: save result...')
    best_weights = study.best_params
    best_score = study.best_value

    state = merge_state(ckpt_path_list, weights=[best_weights[name] for name in ckpt_path_list])
    model.net.load_state_dict(state)
    torch.save(model.net.state_dict(), saved_ckpt_path)

    print(f"best_score = {best_score}")
    print("best_weights:")
    print(best_weights)
    print(f'Optuna soup ckpt saved at path: {saved_ckpt_path}')

    if plot:
        printlog('step3: plot Optuna analysis...')
        optuna.visualization.plot_optimization_history(study).show()
        optuna.visualization.plot_parallel_coordinate(study).show()

    return best_score