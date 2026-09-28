"""
MicroCause core algorithm.

Extracted from RCAEval (https://github.com/phamquiluan/RCAEval),
``RCAEval/e2e/microcause.py``, which is itself modified from the dycause_rca
repository accompanying the paper:

    Meng et al., "MicroCause: Effective End-to-End Root Cause Localization of
    Repeated Performance Issues in Microservice Systems", ISSRE 2020.

Only the essential pipeline is kept:

    PCMCI causal graph (tigramite, ParCorr)
    -> significant-link pruning (alpha_level)
    -> partial-correlation transition matrix Q (pingouin, rho)
    -> random walk from the SLI node
    -> gamma score ranking

The ~2000 lines of SPOT/biSPOT/dSPOT anomaly-detection classes, matplotlib
plotting, and module-level dead code in the original file are omitted (in the
original they only served the disabled SPOT-based eta weighting; eta is fixed
to ones here, exactly as in the RCAEval version).

Adaptations versus the RCAEval version:
  * the input ``data`` DataFrame must already be clean (no ``time`` column,
    numeric, no NaN); the RCAEval ``preprocess`` dependency is removed and
    constant columns are dropped defensively here;
  * ``tau_max``, ``pc_alpha``, ``alpha_level``, ``rho``, walk length and the
    random seed are exposed as parameters;
  * partial-correlation failures (singular covariance with many confounders)
    fall back to 0.0 instead of propagating NaN into the transition matrix.
"""

import networkx as nx
import numpy as np
import pandas as pd
from pingouin import partial_corr
from tigramite import data_processing as pp
from tigramite.independence_tests.parcorr import ParCorr
from tigramite.pcmci import PCMCI


def randomwalk(P, epochs, start_node, teleportation_prob, walk_step=50, print_trace=False):
    """Verbatim from RCAEval e2e/microcause.py (teleportation_prob is unused upstream)."""
    n = P.shape[0]
    score = np.zeros([n])
    current = start_node - 1
    for epoch in range(epochs):
        current = start_node - 1
        if print_trace:
            print("\n{:2d}".format(current + 1), end="->")
        for step in range(walk_step):
            if np.sum(P[current]) == 0:
                break
            else:
                next_node = np.random.choice(range(n), p=P[current])
                if print_trace:
                    print("{:2d}".format(current + 1), end="->")
                score[next_node] += 1
                current = next_node
    label = [i for i in range(n)]
    score_list = list(zip(label, score))
    score_list.sort(key=lambda x: x[1], reverse=True)
    return score_list


def microcause(
    data: pd.DataFrame,
    sli: str,
    tau_max: int = 10,
    pc_alpha: float = 0.1,
    alpha_level: float = 0.001,
    rho: float = 0.2,
    epochs: int = 1000,
    walk_step: int = 1000,
    lambda_param: float = 0.5,
    seed: int = 0,
):
    """Run MicroCause on a wide KPI DataFrame.

    Parameters
    ----------
    data : pd.DataFrame
        Wide time-series frame: one row per timestamp, one column per
        ``{entity}_{metric}`` KPI series. Must NOT contain a ``time`` column.
    sli : str
        Name of the column that acts as the service level indicator; the
        random walk starts from this node.
    Returns
    -------
    dict with keys ``adj`` (0/1 dense adjacency), ``node_names``, ``ranks``
    (column names sorted by descending suspiciousness).
    """
    # defensive cleaning (adapter already guarantees this)
    data = data.loc[:, data.columns[data.std(numeric_only=True) > 0]]
    np_data = data.to_numpy().astype(float)
    node_names = data.columns.to_list()

    if sli not in node_names:
        raise ValueError(f"SLI column '{sli}' not present in data")
    frontend = [node_names.index(sli) + 1]

    # SPOT-based anomaly magnitude weighting is disabled upstream as well.
    eta = np.ones([len(node_names)])

    def get_Q_matrix_part_corr(g, rho=0.2):
        df = data

        def get_part_corr(x, y):
            cond = get_confounders(y)
            if x in cond:
                cond.remove(x)
            if y in cond:
                cond.remove(y)
            try:
                ret = partial_corr(
                    data=df,
                    x=df.columns[x],
                    y=df.columns[y],
                    covar=[df.columns[_] for _ in cond],
                    method="pearson",
                )
                val = abs(float(ret.r))
            except Exception:
                val = 0.0
            if not np.isfinite(val):
                val = 0.0
            return val

        # Calculate the parent nodes set.
        pa_set = {}
        for e in g.edges():
            if e[0] == e[1]:
                continue
            if e[1] not in pa_set:
                pa_set[e[1]] = set([e[0]])
            else:
                pa_set[e[1]].add(e[0])
        for n in g.nodes():
            if n not in pa_set:
                pa_set[n] = set([])

        def get_confounders(j: int):
            ret = pa_set[frontend[0] - 1].difference([j])
            ret = ret.union(pa_set[j])
            return ret

        Q = np.zeros([len(node_names), len(node_names)])
        for e in g.edges():
            if e[0] == e[1]:
                continue
            # e[0] --> e[1]: cause --> result
            # Forward step.
            if frontend[0] - 1 != e[0]:
                Q[e[1], e[0]] = get_part_corr(frontend[0] - 1, e[0])
            # Backward step.
            backward_e = (e[1], e[0])
            if backward_e not in g.edges() and frontend[0] - 1 != e[1]:
                Q[e[0], e[1]] = rho * get_part_corr(frontend[0] - 1, e[1])

        adj = np.asarray(nx.adjacency_matrix(g).todense())
        for i in range(len(node_names)):
            # Calculate P_pc^max
            P_pc_max = []
            for k in adj[:, i].nonzero()[0]:
                if frontend[0] - 1 != k:
                    P_pc_max.append(get_part_corr(frontend[0] - 1, k))
            P_pc_max = np.max(P_pc_max) if len(P_pc_max) > 0 else 0

            if frontend[0] - 1 != i:
                q_ii = get_part_corr(frontend[0] - 1, i)
                Q[i, i] = q_ii - P_pc_max if q_ii > P_pc_max else 0

        l = []
        for i in np.sum(Q, axis=1):
            l.append(1.0 / i if i > 0 else 0.0)
        l = np.diag(l)
        Q = np.dot(l, Q)
        return Q

    def run_pcmci(arr, pc_alpha=0.1, verbosity=0):
        dataframe = pp.DataFrame(arr)
        cond_ind_test = ParCorr()
        pcmci = PCMCI(dataframe=dataframe, cond_ind_test=cond_ind_test, verbosity=verbosity)
        pcmci_res = pcmci.run_pcmci(tau_max=tau_max, pc_alpha=pc_alpha)
        return pcmci, pcmci_res

    pcmci, pcmci_res = run_pcmci(np_data, pc_alpha=pc_alpha, verbosity=0)

    def get_links(pcmci, results, alpha_level=0.01):
        # tigramite >=5 removed return_significant_links(); replicate its
        # semantics: significant lagged links are p_matrix entries below
        # alpha_level (tau >= 1, i.e. include_lagzero_links=False).
        p_matrix = results["p_matrix"]
        n_vars, _, n_tau = p_matrix.shape
        link_dict = {
            j: [(i, -tau)
                for i in range(n_vars)
                for tau in range(1, n_tau)
                if p_matrix[i, j, tau] < alpha_level]
            for j in range(n_vars)
        }
        g = nx.DiGraph()
        for i in range(len(node_names)):
            g.add_node(i)
        for n, links in link_dict.items():
            for l in links:
                g.add_edge(n, l[0])
        return g

    g = get_links(pcmci, pcmci_res, alpha_level=alpha_level)
    Q = get_Q_matrix_part_corr(g, rho=rho)

    np.random.seed(seed)
    vis_list = randomwalk(Q, epochs, frontend[0], teleportation_prob=0, walk_step=walk_step)

    def get_gamma(score_list, eta, lambda_param=0.8):
        gamma = [0 for _ in range(len(node_names))]
        max_vis_time = np.max([i[1] for i in score_list])
        max_eta = np.max(eta)
        if max_vis_time <= 0:  # walk never left the SLI node: all visits are 0
            max_vis_time = 1.0
        if max_eta <= 0:
            max_eta = 1.0
        for n, vis in score_list:
            gamma[n] = lambda_param * vis / max_vis_time + (1 - lambda_param) * eta[n] / max_eta
        return gamma

    gamma = get_gamma(vis_list, eta, lambda_param=lambda_param)

    score_list = sorted(
        zip([(i + 1) for i in range(len(node_names))], gamma), key=lambda x: x[1], reverse=True
    )

    ranks = []
    for r in score_list:
        r = r[0]
        ranks.append(node_names[r - 1])

    return {
        "adj": np.asarray(nx.adjacency_matrix(g).todense()),
        "node_names": node_names,
        "ranks": ranks,
    }
