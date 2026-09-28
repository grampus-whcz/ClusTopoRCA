"""
CIRCA core algorithm.

Extracted from RCAEval (https://github.com/phamquiluan/RCAEval), consolidating
the following upstream files (only the parts CIRCA actually uses):

    RCAEval/e2e/circa.py                 (entry point)
    RCAEval/graph_construction/pc.py     (pc_default: PC algorithm, causal-learn)
    RCAEval/graph_heads/rht.py           (regression-based hypothesis testing)
    RCAEval/graph_heads/random_walk.py   (Score / Scorer base classes)
    RCAEval/classes/graph.py             (Node / MemoryGraph)
    RCAEval/classes/data.py              (CaseData / MemoryDataLoader)

Paper:

    Li et al., "Causal Inference-Based Root Cause Analysis for Online Service
    Systems with Intervention Recognition", KDD 2022.

Pipeline: PC causal discovery over the KPI series -> regression-based
hypothesis testing (RHT): each node is regressed on its parents over a normal
(training) window; the max z-score of the regression residuals in the fault
(testing) window is the suspiciousness score.

Adaptations versus the RCAEval version (all window semantics unchanged):
  * the RCAEval ``preprocess`` dependency is removed; the input frame must be
    clean (the adapter guarantees this) — constant columns are dropped here;
  * the RCAEval implementation assumes high-frequency data and hardcodes
    ``interval=1s, lookup_window=120, detect_window=10, current=inject+300``.
    OpenRCA telemetry is minute-level, so the interval and window sizes are
    exposed as parameters; our defaults are ``interval=60s, lookup_window=30,
    detect_window=5, horizon=300s`` (train on [inject-30min, inject-5min],
    test on the 5 points up to inject+5min);
  * ``MemoryGraph.dump/load`` (JSON persistence) is dropped to keep the
    extraction self-contained.
"""

import logging
from abc import ABC
from datetime import timedelta
from typing import Callable, Dict, List, Sequence, Set, Tuple, Union

import networkx as nx
import numpy as np
import pandas as pd
from causallearn.search.ConstraintBased.PC import pc
from scipy.stats import norm
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler


# ---------------------------------------------------------------------------
# graph_heads/random_walk.py : Score / Scorer
# ---------------------------------------------------------------------------
class Score:
    """The more suspicious a node, the higher the score."""

    def __init__(self, score: float, info: dict = None, key: tuple = None):
        self._score = score
        self._key = key
        self._info = {} if info is None else info

    def __eq__(self, obj) -> bool:
        if isinstance(obj, Score):
            return self.score == obj.score
        return False

    def __getitem__(self, key: str):
        return self._info[key]

    def __setitem__(self, key: str, value):
        self._info[key] = value

    def get(self, key: str, default=None):
        return self._info.get(key, default)

    @property
    def score(self) -> float:
        return self._score

    @score.setter
    def score(self, value: float):
        self._score = value

    @property
    def key(self) -> float:
        return self.score if self._key is None else self._key

    @key.setter
    def key(self, value: tuple):
        self._key = value

    @property
    def info(self) -> dict:
        return self._info

    def update(self, score: "Score") -> "Score":
        self._info.update(score.info)
        self.score = score.score
        self.key = score.key
        return self

    def asdict(self) -> Dict[str, Union[float, dict, tuple]]:
        data = {"score": self._score, "info": {**self._info}}
        if self._key is not None:
            data["key"] = self._key
        return data

    def __repr__(self) -> str:
        return str(self.asdict())


class Scorer(ABC):
    """The abstract interface to score nodes."""

    def __init__(
        self,
        aggregator: Callable[[Sequence[float]], float] = max,
        max_workers: int = 1,
        seed: int = 0,
        cuda: bool = False,
    ):
        self._aggregator = aggregator
        self._max_workers = max_workers
        self._seed = seed
        self._cuda = cuda

    def score(self, graph: "Graph", data: "CaseData", current: float,
              scores: Dict["Node", "Score"] = None) -> Dict["Node", "Score"]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# classes/graph.py : Node / Graph / MemoryGraph
# ---------------------------------------------------------------------------
class Node:
    """The element of a graph."""

    def __init__(self, entity: str, metric: str):
        self._entity = entity
        self._metric = metric

    @property
    def entity(self) -> str:
        return self._entity

    @property
    def metric(self) -> str:
        return self._metric

    def asdict(self) -> Dict[str, str]:
        return {"entity": self.entity, "metric": self.metric}

    def __eq__(self, obj: object) -> bool:
        if isinstance(obj, Node):
            return self.entity == obj.entity and self.metric == obj.metric
        return False

    def __hash__(self) -> int:
        return hash((self.entity, self.metric))

    def __repr__(self) -> str:
        return f"Node{(self.entity, self.metric)}"


class Graph(ABC):
    """The abstract interface to access relations."""

    def __init__(self):
        self._nodes: Set[Node] = set()

    @property
    def nodes(self) -> Set[Node]:
        return self._nodes

    def children(self, node: Node, **kwargs) -> Set[Node]:
        raise NotImplementedError

    def parents(self, node: Node, **kwargs) -> Set[Node]:
        raise NotImplementedError


class MemoryGraph(Graph):
    """Implement Graph with data in memory."""

    def __init__(self, graph: nx.DiGraph):
        super().__init__()
        self._graph = graph
        self._nodes.update(self._graph.nodes)

    def children(self, node: Node, **kwargs) -> Set[Node]:
        if not self._graph.has_node(node):
            return set()
        return set(self._graph.successors(node))

    def parents(self, node: Node, **kwargs) -> Set[Node]:
        if not self._graph.has_node(node):
            return set()
        return set(self._graph.predecessors(node))


# ---------------------------------------------------------------------------
# classes/data.py : DataLoader / MemoryDataLoader / CaseData
# ---------------------------------------------------------------------------
class DataLoader(ABC):
    """The abstract interface to access data."""

    @property
    def entities(self) -> Sequence[str]:
        raise NotImplementedError

    @property
    def metrics(self) -> Dict[str, Sequence[str]]:
        raise NotImplementedError

    @property
    def nodes(self) -> Sequence[Node]:
        return [
            Node(entity=entity, metric=metric)
            for entity, metrics in self.metrics.items()
            for metric in metrics
        ]

    def load(self, entity: str, metric: str, start: float, end: float,
             interval: timedelta, **kwargs) -> Union[None, Sequence[float]]:
        raise NotImplementedError

    @staticmethod
    def preprocess(
        time_series: Sequence[Tuple[float, float]],
        start: float,
        end: float,
        interval: timedelta,
        **kwargs,
    ) -> Sequence[float]:
        """
        Truncate the time series and fill missing data points.

        This method is edited from k-Shape, which is released under the MIT
        license. See https://github.com/sieve-microservices/kshape
        """
        if not time_series:
            return None
        data: np.ndarray = np.array(time_series)
        # 1. Truncate the time series and make sure that [start, end] is the boundry
        data = data[(data[:, 0] >= start) & (data[:, 0] <= end), :]
        if len(data) == 0:
            return None
        data = np.vstack([data, np.array([(start, np.nan), (end, np.nan)])])

        # 2. Fill missing data points with fixed frequency
        data_frame = pd.DataFrame(data)
        data_frame[0] = pd.to_datetime(data_frame[0], unit=kwargs.get("unit", "s"), utc=True)
        data_frame: pd.DataFrame = data_frame.set_index(0).resample(interval, origin="start").mean()
        data_frame.interpolate(method="time", limit_direction="both", inplace=True)
        data_frame.bfill(inplace=True)

        # 3. Return values only
        data_frame.sort_index(inplace=True)
        return tuple(data_frame[1])


class MemoryDataLoader(DataLoader):
    """Implement DataLoader with data in memory."""

    def __init__(self, data: Dict[str, Dict[str, Sequence[Tuple[float, float]]]]):
        self._data = data

    @property
    def entities(self) -> Sequence[str]:
        return tuple(self._data.keys())

    @property
    def metrics(self) -> Dict[str, Sequence[str]]:
        return {entity: tuple(metrics.keys()) for entity, metrics in self._data.items()}

    def load(self, entity: str, metric: str, start: float, end: float,
             interval: timedelta, **kwargs) -> Union[None, Sequence[float]]:
        if entity not in self._data or metric not in self._data[entity]:
            return None
        return self.preprocess(
            time_series=self._data[entity][metric],
            start=start,
            end=end,
            interval=interval,
            **kwargs,
        )


class CaseData:
    """Case data that algorithms can access."""

    def __init__(
        self,
        data_loader: DataLoader,
        sli: Node,
        detect_time: float,
        interval: timedelta = timedelta(minutes=1),
        lookup_window: int = 120,
        detect_window: int = 10,
        prune: bool = True,
    ):
        self._data_loader = data_loader
        self._sli = sli
        self._detect_time = detect_time

        # Parameters for the algorithm
        self._interval = interval
        self._train_window = lookup_window - detect_window + 1
        self._test_window = detect_window
        self._lookup_window = lookup_window * interval.total_seconds()
        self._prune = prune

    @property
    def data_loader(self) -> DataLoader:
        return self._data_loader

    @property
    def sli(self) -> Node:
        return self._sli

    @property
    def detect_time(self) -> float:
        return self._detect_time

    @property
    def train_window(self) -> int:
        return self._train_window

    @property
    def test_window(self) -> int:
        return self._test_window

    def load_data(self, graph: Graph = None, current: float = None) -> Dict[Node, Sequence[float]]:
        if current is None:
            current = self._detect_time
        else:
            current = max(current, self._detect_time)
        nodes = self._data_loader.nodes if graph is None else graph.nodes

        start = self._detect_time - self._lookup_window
        length = int((current - start) / self._interval.total_seconds()) + 1
        series: Dict[Node, Sequence[float]] = {}
        for node in nodes:
            node_data = self._data_loader.load(
                entity=node.entity,
                metric=node.metric,
                start=start,
                end=current,
                interval=self._interval,
            )
            if self._prune:
                if node_data and len(set(node_data)) > 1:
                    series[node] = node_data[:length]
            else:
                if not node_data:
                    node_data = np.zeros(length)
                series[node] = node_data[:length]
        return series


# ---------------------------------------------------------------------------
# graph_heads/rht.py : regression-based hypothesis testing
# ---------------------------------------------------------------------------
def zscore(train_y: np.ndarray, test_y: np.ndarray) -> np.ndarray:
    """
    Estimate to what extend each value in test_y violates
    the normal distribution defined by train_y
    """
    scaler = StandardScaler().fit(train_y.reshape(-1, 1))
    return scaler.transform(test_y.reshape(-1, 1))[:, 0]


def zscore_conf(score: float) -> float:
    """Convert z-score into confidence about the hypothesis the score is abnormal."""
    return 1 - 2 * norm.cdf(-abs(score))


class DecomposableScorer(Scorer):
    """Score each node separately."""

    def score_node(self, graph: Graph, series: Dict[Node, Sequence[float]],
                   node: Node, data: CaseData) -> Score:
        raise NotImplementedError

    def _score(self, candidates: Sequence[Node], series: Dict[Node, Sequence[float]],
               graph: Graph, data: CaseData):
        results: Dict[Node, Score] = {}
        for node in candidates:
            score = self.score_node(graph, series, node, data)
            if score is not None:
                results[node] = score
        return results

    def score(self, graph: Graph, data: CaseData, current: float,
              scores: Dict[Node, Score] = None) -> Dict[Node, Score]:
        series = data.load_data(graph, current)
        candidates = list(series.keys()) if scores is None else list(scores.keys())

        results = self._score(candidates=candidates, series=series, graph=graph, data=data)

        if scores is None:
            return results
        return {node: scores[node].update(score) for node, score in results.items()}


class Regressor(ABC):
    """Regress one node on its parents, assuming x ~ P(x | pa(X))."""

    def __init__(self):
        klass = self.__class__
        self._logger = logging.getLogger(f"{klass.__module__}.{klass.__name__}")

    @staticmethod
    def _zscore(train_y: np.ndarray, test_y: np.ndarray) -> np.ndarray:
        return zscore(train_y=train_y, test_y=test_y)

    def _score(self, train_x: np.ndarray, test_x: np.ndarray,
               train_y: np.ndarray, test_y: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def score(self, train_x: np.ndarray, test_x: np.ndarray,
              train_y: np.ndarray, test_y: np.ndarray) -> np.ndarray:
        if len(train_x) == 0:
            return self._zscore(train_y=train_y, test_y=test_y)
        try:
            return self._score(train_x=train_x, test_x=test_x, train_y=train_y, test_y=test_y)
        except ValueError as err:
            self._logger.warning(err, exc_info=True)
            return self._zscore(train_y=train_y, test_y=test_y)


class ANMRegressor(Regressor):
    """
    Regress one node on its parents with an Additive Noise Model
    assuming x = f(pa(X)) + e and e follows a normal distribution.
    """

    def __init__(self, regressor=None, **kwargs):
        super().__init__(**kwargs)
        self._regressor = regressor if regressor else LinearRegression()

    def _score(self, train_x: np.ndarray, test_x: np.ndarray,
               train_y: np.ndarray, test_y: np.ndarray) -> np.ndarray:
        self._regressor.fit(train_x, train_y)
        train_err: np.ndarray = train_y - self._regressor.predict(train_x)
        test_err: np.ndarray = test_y - self._regressor.predict(test_x)
        return self._zscore(train_y=train_err, test_y=test_err)


class RHTScorer(DecomposableScorer):
    """Scorer with regression-based hypothesis testing."""

    def __init__(self, tau_max: int = 0, regressor: Regressor = None,
                 use_confidence: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._tau_max = max(tau_max, 0)
        self._regressor = regressor if regressor else ANMRegressor()
        self._use_confidence = use_confidence

    @staticmethod
    def _split_train_test(series_x: np.ndarray, series_y: np.ndarray,
                          train_window: int, test_window: int):
        train_x: np.ndarray = series_x[:train_window, :]
        train_y: np.ndarray = series_y[:train_window]
        test_x: np.ndarray = series_x[-test_window:, :]
        test_y: np.ndarray = series_y[-test_window:]
        return train_x, test_x, train_y, test_y

    def split_data(self, data: Dict[Node, Sequence[float]], node: Node,
                   parents: Sequence[Node], case_data: CaseData
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        series = np.array([data[parent] for parent in parents if parent in data]).T
        if len(series) == 0:
            series = np.zeros((0, 0))
        series_x = np.hstack([np.roll(series, i, 0) for i in range(self._tau_max + 1)])
        series_x: np.ndarray = series_x[self._tau_max :, :]
        series_y = np.array(data[node][self._tau_max :])

        return self._split_train_test(
            series_x=series_x,
            series_y=series_y,
            train_window=case_data.train_window - self._tau_max,
            test_window=case_data.test_window,
        )

    def score_node(self, graph: Graph, series: Dict[Node, Sequence[float]],
                   node: Node, data: CaseData) -> Score:
        parents = list(graph.parents(node))

        train_x, test_x, train_y, test_y = self.split_data(series, node, parents, data)
        z_scores = self._regressor.score(
            train_x=train_x, test_x=test_x, train_y=train_y, test_y=test_y
        )
        z_score = self._aggregator(abs(z_scores))
        confidence = zscore_conf(z_score)
        if self._use_confidence:
            score = Score(confidence)
            score.key = (score.score, z_score)
        else:
            score = Score(z_score)
        score["z-score"] = z_score
        score["Confidence"] = confidence

        return score


def rht(adj: np.ndarray, inject_time: int, data: pd.DataFrame,
        interval_s: int = 60, lookup_window: int = 30, detect_window: int = 5,
        horizon_s: int = 300) -> List[Tuple[str, float]]:
    """Regression-based hypothesis testing over a PC-derived causal graph.

    adj : causal-learn adjacency matrix (cg.G.graph)
    inject_time : unix seconds of the fault alert
    data : wide DataFrame with a ``time`` column (unix seconds) and one
        ``{entity}_{metric}`` column per KPI series. Both entity and metric
        names must be free of ``_`` (the adapter sanitizes them).
    interval_s / lookup_window / detect_window / horizon_s : analysis
        resolution and windowing (see module docstring for our defaults).

    return: list of (column_name, score), sorted by descending score.
    """
    node_names = data.columns.to_list()

    # == prepare the graph
    nodes = [Node(name.split("_")[0], name.split("_")[1]) for name in node_names if name != "time"]
    graph = nx.DiGraph()

    node_num = len(adj)
    for a in range(node_num):
        for b in range(node_num):
            # case 1: no edge
            if adj[a, b] == adj[b, a] == 0:
                pass
            # case 2: undirected a -- b
            elif adj[a, b] == adj[b, a] == -1:
                graph.add_edge(nodes[b], nodes[a])
            # case 3: directed a->b
            elif adj[a, b] == 1 and adj[b, a] == -1:
                graph.add_edge(nodes[b], nodes[a])
            # case 4: directed b->a
            elif adj[a, b] == -1 and adj[b, a] == 1:
                graph.add_edge(nodes[a], nodes[b])
            else:
                raise ValueError(f"Unexpected value: {adj[a, b]}, {adj[b, a]}")

    graph = graph.reverse()
    mem_graph = MemoryGraph(graph)
    # == end prepare the graph

    scorer = RHTScorer()
    scores: Dict[Node, Score] = None

    timestamps = data["time"]
    sli = np.random.choice(nodes)  # kept from upstream; unused by the scorer
    services = list(set([c.split("_")[0] for c in data.columns if c != "time"]))
    metrics = list(set([c.split("_")[1] for c in data.columns if c != "time"]))
    out_data = {s: {} for s in services}
    for s in services:
        for m in metrics:
            try:
                out_data[s][m] = list(zip(timestamps, data[f"{s}_{m}"]))
            except Exception:
                pass
    mem_data_loader = MemoryDataLoader(out_data)

    data = CaseData(
        data_loader=mem_data_loader,
        sli=sli,
        detect_time=inject_time,
        interval=timedelta(seconds=interval_s),
        lookup_window=lookup_window,
        detect_window=detect_window,
    )

    scores = scorer.score(graph=mem_graph, data=data, current=inject_time + horizon_s, scores=scores)
    scores = sorted(scores.items(), key=lambda item: item[1].key, reverse=True)
    output = []
    for item in scores:
        output.append((f"{item[0].entity}_{item[0].metric}", item[1].score))

    return output


# ---------------------------------------------------------------------------
# graph_construction/pc.py : pc_default
# ---------------------------------------------------------------------------
def pc_default(data: pd.DataFrame, show_progress: bool = False, **kwargs) -> np.ndarray:
    """PC algorithm (causal-learn, fisher-z default) over the KPI columns."""
    node_names = data.columns.to_list()
    cg = pc(
        data.to_numpy().astype(float),
        node_names=node_names,
        show_progress=show_progress,
        background_knowledge=None,
    )
    return cg.G.graph


# ---------------------------------------------------------------------------
# e2e/circa.py : entry point
# ---------------------------------------------------------------------------
def _drop_degenerate(df: pd.DataFrame, corr_thresh: float = 0.999) -> pd.DataFrame:
    """Drop columns that make the sample correlation matrix singular.

    The fisher-z CI test used by the PC algorithm aborts on singular or
    numerically singular correlation matrices (which occur easily with
    minute-level telemetry: near-constant error counters, duplicated gauges,
    more variables than samples). We drop constant/near-constant columns and
    greedily remove one side of any near-perfectly correlated pair, then keep
    dropping the column with the largest mean absolute correlation until the
    correlation matrix is full rank.
    """
    df = df.loc[:, df.columns[df.std(numeric_only=True) > 1e-8]]
    if df.shape[1] < 2:
        return df
    corr = df.corr().abs()
    cols = list(df.columns)
    to_drop = set()
    for i in range(len(cols)):
        if cols[i] in to_drop:
            continue
        for j in range(i + 1, len(cols)):
            if cols[j] not in to_drop and corr.iloc[i, j] >= corr_thresh:
                to_drop.add(cols[j])
    df = df.drop(columns=list(to_drop))
    while df.shape[1] >= 2:
        c = np.corrcoef(df.to_numpy().astype(float).T)
        if np.linalg.matrix_rank(c, tol=1e-10) >= c.shape[0] and df.shape[1] < df.shape[0]:
            break
        mean_corr = pd.DataFrame(np.abs(c), index=df.columns, columns=df.columns).mean()
        df = df.drop(columns=[mean_corr.idxmax()])
    return df


def circa(data: pd.DataFrame, inject_time: int, **kwargs) -> Dict:
    """Run CIRCA on a wide KPI DataFrame.

    data must contain a ``time`` column (unix seconds) plus one
    ``{entity}_{metric}`` column per KPI series.
    """
    time_col = data["time"]
    pc_input = data.drop(columns=["time"])
    pc_input = _drop_degenerate(pc_input)
    pc_input = pc_input.dropna(axis=0)
    node_names = pc_input.columns.to_list()

    adj = pc_default(pc_input)
    frame = pc_input.copy()
    frame["time"] = time_col
    ranks = rht(adj, inject_time, frame, **kwargs)
    ranks = sorted(ranks, key=lambda x: x[1], reverse=True)
    ranks = [x[0] for x in ranks]
    return {"adj": adj, "node_names": node_names, "ranks": ranks}
