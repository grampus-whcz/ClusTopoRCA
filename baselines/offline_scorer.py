"""
Offline reproduction of ClusTopoRCA's topology scoring ranker (stage 3 of the
pipeline), used to build the *w/o LLM* variant and the *RHT-fused* variant for
the reviewer-response experiments.  No LLM is involved anywhere.

What this module replicates (verified against the source scripts and the tool
agents that the paper pipeline actually invokes —
``camel/agents/tool_agents/*_5tools_fast*.py``):

* Bank    -> ``OmniTransfer_new/Bank_utils/Bank_cluster_window_analyze_anomalies_2.7.py``
             weights W_time=0.3, W_topo=0.4, W_count=0.3 (no component-weight
             multiplication in code); concentration window 4 min starting at
             the 3rd distinct anomaly timestamp (``ANALYSIS_START_TIMESTAMP_INDEX=2``);
             candidate filter count>=2, fallback >=1; hardcoded call-chain
             topology; in-degree score reversed (1 - in/max_in); reachable
             count = |descendants ∩ candidates| + 1.
* Telecom -> ``OmniTransfer_new/Telecom_utils/14.Telecom_cluster_window_analyze_anomalies.3.3.py``
             active "tune5" block: W_time=0.025, W_topo=0.025, W_count=0.95
             (exactly the paper's commented defaults), multiplied by
             component_weight db=1.0 / os=0.9 / docker=0.85 (unknown 0.5);
             window 5 min from the 3rd distinct timestamp; filter count>=1;
             dynamic topology from ``experiment/RQ2/all_telecom_unique_dependency_graphs.json``
             (bidirectional) plus default os<->docker / os<->db host edges;
             in-degree score NOT reversed (in/max_in, code-as-run); reachable
             count = |all descendants| (no +1).
* Market  -> ``OmniTransfer_new/Market_utils/15.Market_cluster_window_analyze_anomalies_3.3.py``
             weights W_time=0.1, W_topo=0.8, W_count=0.1 (no component-weight
             multiplication); window 5 min from the 1st distinct timestamp
             (index 0); filter count>=3, fallback >=1; static Online-Boutique
             topology (bidirectional) with entity-name cleaning; in-degree
             reversed; reachable = |descendants ∩ candidates| + 1.

All three use DBSCAN(eps=60s, min_samples=3) on anomaly timestamps — the
parameters the tool agents pass (min_samples="3", eps default 60) and the
footers of the cached cluster reports in 1204/ and 1215/c3/.

Anomaly loading follows each script's loader exactly:
* Bank:   per-window npys (metric_app / metric_container / trace / log), log
          attribute = ``PatternID_<id>``; dedup (type, entity, attr, ts).
* Telecom: per-window npys (metric_A / metric_B / trace); metric_A keeps only
          (entity, attribute) groups occurring >=4 times; trace edges "a->b"
          are exploded into two records with attribute ``trace_<attr>``.
* Market: full-day npys (``*_0000_2400.npy``) filtered to [ws, we); per
          modality only the single most frequent (entity, attribute) group
          with frequency >=4 is kept (entity-unique greedy top-1).
          Note: the original script derives [ws, we) from the date+suffix
          strings and breaks on cross-midnight windows (end 00:00 < start);
          we use the correctly parsed query window instead (only deviation,
          affects "2330_0000" style windows).

Cross-cluster merge (the deterministic LLM replacement for the w/o-LLM
variant): clusters are ordered by total anomaly count (desc); the merged
entity ranking is the primary cluster's scored candidate list, then the
remaining clusters' unseen candidates in order.  An entity's score record is
taken from the first cluster in which it appears.  The predicted fault time
is the primary cluster's earliest anomaly timestamp; the predicted fault
reason is mapped from the top-1 entity's dominant anomaly attributes to the
record.csv reason vocabulary via per-dataset keyword rules.

Entity names produced by the scorers are aligned to the official candidate
inventory (``openrca_data.candidate_inventory``) with deterministic rules
(strip ":..." suffixes, "node-X.pod" -> pod, "a.destination.b.c" -> a,
strip -grpc/-http/-external, ...).  Raw entities with no inventory match
(e.g. ServiceTest*, ROOT, UNKNOWN_PARENT, redis_*) are dropped from the
final ranking, exactly as the LLM was constrained to the candidate list.
"""

import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# Ablation switch for the in-degree direction (paper's assumption: lower
# in-degree = more upstream = more suspicious; Bank/Market reverse it, Telecom
# does not).  Set True to flip every dataset's direction (B-4 experiment).
IN_DEGREE_FLIP = False

OMNITRANSFER_ROOT = os.environ.get(
    "OMNITRANSFER_ROOT", "/root/shared-nvme/work/timeSeries/OmniTransfer_new")
ARTIFACT_DIR = {"Bank": "1204", "Telecom": "1216", "Market-1": "1215", "Market-2": "1215"}

TZ8 = timezone(timedelta(hours=8))

DBSCAN_EPS_SECONDS = 60
DBSCAN_MIN_SAMPLES = 3


# ---------------------------------------------------------------------------
# window -> artifact naming (mirrors controller.py parse_*_rca_task)
# ---------------------------------------------------------------------------
def window_names(ws: int, we: int):
    """unix window -> (date_online, output_suffix) used in artifact filenames."""
    s = datetime.fromtimestamp(ws, tz=TZ8)
    e = datetime.fromtimestamp(we, tz=TZ8)
    return s.strftime("%Y_%m_%d"), f"{s.strftime('%H%M')}_{e.strftime('%H%M')}"


# ---------------------------------------------------------------------------
# per-dataset anomaly loaders (faithful to the original scripts)
# ---------------------------------------------------------------------------
def _load_npy(path):
    if not os.path.exists(path):
        return None
    try:
        return np.load(path, allow_pickle=True)
    except Exception:
        return None


def _dedup_sort(anomalies):
    seen, out = set(), []
    for a in anomalies:
        key = (a["type"], a["entity"], a["attribute"], a["ts"])
        if key not in seen:
            seen.add(key)
            out.append(a)
    out.sort(key=lambda x: x["ts"])
    return out


def load_bank_anomalies(ws, we):
    date_str, suffix = window_names(ws, we)
    base = os.path.join(OMNITRANSFER_ROOT, ARTIFACT_DIR["Bank"])
    anomalies = []
    specs = [
        ("metric_app", f"Bank_metric_app_anomalies_{date_str}_{suffix}.npy"),
        ("metric_container", f"Bank_metric_container_anomalies_{date_str}_{suffix}.npy"),
        ("trace", f"Bank_trace_anomalies_{date_str}_{suffix}.npy"),
        ("log", f"Bank_log_anomalies_{date_str}_{suffix}.npy"),
    ]
    for typ, fname in specs:
        data = _load_npy(os.path.join(base, fname))
        if data is None:
            continue
        for item in data:
            if typ == "log":
                pod, pattern_id, template, ts = item
                anomalies.append({"ts": int(ts), "type": "log", "entity": str(pod),
                                  "attribute": f"PatternID_{pattern_id}", "raw": str(template)})
            else:
                entity, attr, ts = item[0], item[1], item[2]
                anomalies.append({"ts": int(ts), "type": typ, "entity": str(entity),
                                  "attribute": str(attr), "raw": ""})
    return _dedup_sort(anomalies)


def load_telecom_anomalies(ws, we):
    date_str, suffix = window_names(ws, we)
    base = os.path.join(OMNITRANSFER_ROOT, ARTIFACT_DIR["Telecom"])
    raw = []
    specs = [
        ("metric_A", f"Telecom_metric_A_anomalies_{date_str}_{suffix}.npy"),
        ("metric_B", f"Telecom_metric_B_anomalies_{date_str}_{suffix}.npy"),
        ("trace", f"Telecom_trace_anomalies_{date_str}_{suffix}.npy"),
    ]
    for typ, fname in specs:
        data = _load_npy(os.path.join(base, fname))
        if data is None:
            continue
        for item in data:
            entity, attr, ts = str(item[0]), str(item[1]), int(item[2])
            if typ == "trace" and "->" in entity:
                source, target = entity.split("->")
                raw.append({"ts": ts, "type": "trace", "entity": source,
                            "attribute": f"trace_{attr}", "raw": entity})
                raw.append({"ts": ts, "type": "trace", "entity": target,
                            "attribute": f"trace_{attr}", "raw": entity})
            else:
                raw.append({"ts": ts, "type": typ, "entity": entity,
                            "attribute": attr if typ != "trace" else f"trace_{attr}",
                            "raw": entity if typ == "trace" else ""})
    # metric_A: keep only (entity, attribute) groups occurring >= 4 times
    groups = defaultdict(list)
    others = []
    for a in raw:
        if a["type"] == "metric_A":
            groups[(a["entity"], a["attribute"])].append(a)
        else:
            others.append(a)
    anomalies = [a for items in groups.values() if len(items) >= 4 for a in items] + others
    return _dedup_sort(anomalies)


_MARKET_DAY_CACHE = {}


def _market_day_anomalies(date_str):
    """Load and parse the full-day Market anomaly npys (cached per day)."""
    if date_str in _MARKET_DAY_CACHE:
        return _MARKET_DAY_CACHE[date_str]
    base = os.path.join(OMNITRANSFER_ROOT, ARTIFACT_DIR["Market-1"])
    anomalies = []
    modalities = ["metric_service", "metric_runtime", "metric_container",
                  "metric_mesh", "metric_node", "trace", "log"]
    for typ in modalities:
        fname = f"Market_{typ}_anomalies_{date_str}_0000_2400.npy"
        data = _load_npy(os.path.join(base, fname))
        if data is None:
            continue
        for item in data:
            if typ == "log":
                pod, pattern_id, template, ts = item
                entity_key, attr_key, raw = str(pod), str(template), str(template)
            else:
                entity, attr, ts = item[0], item[1], item[2]
                entity_key, attr_key, raw = str(entity), str(attr), ""
            anomalies.append({"ts": int(ts), "type": typ, "entity": entity_key,
                              "attribute": attr_key, "raw": raw})
    # NOTE: keep raw (non-deduped) records — the original script counts group
    # frequencies before deduplication.
    _MARKET_DAY_CACHE[date_str] = anomalies
    return anomalies


def load_market_anomalies(ws, we):
    date_str, _ = window_names(ws, we)
    day = _market_day_anomalies(date_str)
    # window filter [ws, we)
    anomalies = [a for a in day if ws <= a["ts"] < we]
    # per modality: keep only the single most frequent (entity, attribute)
    # group with frequency >= 4 (entity-unique greedy top-1)
    final = []
    for typ in sorted(set(a["type"] for a in anomalies)):
        type_an = [a for a in anomalies if a["type"] == typ]
        counter = Counter((a["entity"], a["attribute"]) for a in type_an)
        group_map = defaultdict(list)
        for a in type_an:
            group_map[(a["entity"], a["attribute"])].append(a)
        frequent = sorted(((k, c) for k, c in counter.items() if c >= 4),
                          key=lambda x: x[1], reverse=True)
        seen_entities = set()
        for (entity, attr), freq in frequent:
            if entity in seen_entities:
                continue
            seen_entities.add(entity)
            final.extend(group_map[(entity, attr)])
            break  # at most one group per modality
    return _dedup_sort(final)


LOADERS = {"Bank": load_bank_anomalies, "Telecom": load_telecom_anomalies,
           "Market-1": load_market_anomalies, "Market-2": load_market_anomalies}


def dbscan_clusters(anomalies, eps=DBSCAN_EPS_SECONDS, min_samples=DBSCAN_MIN_SAMPLES):
    """DBSCAN over anomaly timestamps. Returns (clusters, noise): clusters is a
    list of anomaly lists, ordered by DBSCAN label (i.e. roughly by time)."""
    if not anomalies:
        return [], []
    X = np.array([[a["ts"]] for a in anomalies])
    labels = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean").fit_predict(X)
    clusters, noise = defaultdict(list), []
    for a, lab in zip(anomalies, labels):
        (noise if lab == -1 else clusters[lab]).append(a)
    return [clusters[k] for k in sorted(clusters)], noise


# ---------------------------------------------------------------------------
# Bank scorer (Bank_cluster_window_analyze_anomalies_2.7.py)
# ---------------------------------------------------------------------------
BANK_BASE_EDGES = [
    ("apache01", "IG01"), ("apache01", "IG02"),
    ("apache02", "IG01"), ("apache02", "IG02"),
    ("IG01", "Tomcat02"), ("IG02", "Tomcat02"),
    ("Tomcat02", "MG01"), ("Tomcat02", "MG02"),
    ("MG01", "dockerA2"), ("MG02", "dockerA2"),
    ("dockerA2", "Mysql02"),
    ("Tomcat02", "Redis02"), ("Redis02", "Tomcat02"),
    ("MG01", "Redis02"), ("MG02", "Redis02"), ("Redis02", "MG01"), ("Redis02", "MG02"),
]
BANK_WEIGHTS = {"time": 0.3, "topo": 0.4, "count": 0.3}
BANK_CONC_MINUTES = 4
BANK_START_IDX = 2
BANK_THRESHOLD = 2
BANK_FALLBACK = 1


class BankScorer:
    def __init__(self):
        pass

    def _build_topology(self, anomalies):
        G = nx.DiGraph()
        G.add_edges_from(BANK_BASE_EDGES)
        for a in anomalies:
            if "->" in a["entity"]:
                s, t = a["entity"].split("->")
                if not G.has_edge(s, t):
                    G.add_edge(s, t)
        return G

    def score_cluster(self, cluster, conc_minutes=None):
        """-> DataFrame indexed by entity with score components, or None."""
        cm = BANK_CONC_MINUTES if conc_minutes is None else conc_minutes
        node_ts, edge_pairs = [], []
        node_counts, edge_counts = Counter(), Counter()
        entity_attrs = defaultdict(Counter)
        all_ts = sorted({a["ts"] for a in cluster})
        if not all_ts:
            return None
        t_start = all_ts[BANK_START_IDX] if BANK_START_IDX < len(all_ts) else all_ts[-1]
        t_window = t_start + cm * 60
        for a in cluster:
            if a["ts"] > t_window:
                continue
            ent = a["entity"]
            if "->" in ent:
                s, t = ent.split("->")
                edge_counts[s] += 1
                edge_counts[t] += 1
                edge_pairs.append((s, a["ts"]))
                edge_pairs.append((t, a["ts"]))
                entity_attrs[s][a["attribute"]] += 1
                entity_attrs[t][a["attribute"]] += 1
            else:
                node_counts[ent] += 1
                node_ts.append((ent, a["ts"]))
                entity_attrs[ent][a["attribute"]] += 1
        total = node_counts + edge_counts
        candidates = {e for e, c in total.items() if c >= BANK_THRESHOLD}
        if not candidates:
            candidates = {e for e, c in total.items() if c >= BANK_FALLBACK}
        if not candidates:
            return None

        earliest = {}
        for ent, ts in node_ts + edge_pairs:
            if ent in candidates:
                earliest[ent] = min(earliest.get(ent, np.inf), ts)

        G = self._build_topology(cluster)

        def reachable(ent):
            if ent not in G.nodes:
                return 0
            try:
                desc = nx.descendants(G, ent)
                return len([n for n in desc if n in candidates]) + 1
            except Exception:
                return 0

        rows = []
        for ent in sorted(candidates):
            rows.append({
                "entity": ent,
                "count": total[ent],
                "earliest_ts": earliest.get(ent),
                "in_degree": G.in_degree(ent) if ent in G.nodes else 0,
                "out_degree": G.out_degree(ent) if ent in G.nodes else 0,
                "reachable": reachable(ent),
                "attrs": dict(entity_attrs.get(ent, {})),
            })
        df = pd.DataFrame(rows).dropna(subset=["earliest_ts"])
        if df.empty:
            return None

        t_min, t_max = df["earliest_ts"].min(), df["earliest_ts"].max()
        df["time_score"] = 1.0 if t_min == t_max else (t_max - df["earliest_ts"]) / (t_max - t_min)
        max_in = df["in_degree"].max() or 1
        max_out = df["out_degree"].max() or 1
        max_reach = df["reachable"].max() or 1
        df["topology_score"] = ((df["in_degree"] / max_in if IN_DEGREE_FLIP else 1 - df["in_degree"] / max_in)
                                + df["out_degree"] / max_out
                                + df["reachable"] / max_reach) / 3
        max_count = df["count"].max() or 1
        df["count_score"] = df["count"] / max_count
        df["component_weight"] = 1.0
        df["final_score"] = (BANK_WEIGHTS["time"] * df["time_score"]
                             + BANK_WEIGHTS["topo"] * df["topology_score"]
                             + BANK_WEIGHTS["count"] * df["count_score"])
        return df.sort_values("final_score", ascending=False, kind="mergesort").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Telecom scorer (14.Telecom_cluster_window_analyze_anomalies.3.3.py, tune5)
# ---------------------------------------------------------------------------
TELECOM_WEIGHTS = {"time": 0.025, "topo": 0.025, "count": 0.95}
TELECOM_CONC_MINUTES = 5
TELECOM_START_IDX = 2
TELECOM_THRESHOLD = 1
TELECOM_FALLBACK = 1
TELECOM_COMPONENT_WEIGHTS = {"db": 1.0, "os": 0.9, "docker": 0.85}
TELECOM_DEP_GRAPHS = os.path.join(
    OMNITRANSFER_ROOT, "experiment", "RQ2", "all_telecom_unique_dependency_graphs.json")


def _telecom_component_type(entity):
    m = re.match(r"^(os|docker|db)_\d+$", entity)
    return m.group(1) if m else "unknown"


class TelecomScorer:
    def __init__(self, dep_graphs_path=TELECOM_DEP_GRAPHS):
        import json
        G = nx.DiGraph()
        try:
            with open(dep_graphs_path) as f:
                graphs = json.load(f)
        except Exception:
            graphs = []
        for graph in graphs:
            for edge in graph:
                if len(edge) == 2:
                    G.add_edge(edge[0], edge[1])
                    G.add_edge(edge[1], edge[0])  # bidirectional
        # default OS <-> docker host associations (as in the original script)
        for i in range(1, 9):
            docker = f"docker_{i:03d}"
            os_node = f"os_{(i // 2) + 1:03d}" if (i // 2) + 1 <= 22 else "os_22"
            G.add_edge(os_node, docker)
            G.add_edge(docker, os_node)
        # default DB <-> OS associations
        for i in range(1, 14):
            db = f"db_{i:03d}"
            os_node = f"os_{(i // 2) + 1:03d}" if (i // 2) + 1 <= 22 else "os_22"
            G.add_edge(os_node, db)
            G.add_edge(db, os_node)
        self.topology = G

    def score_cluster(self, cluster, conc_minutes=None):
        cm = TELECOM_CONC_MINUTES if conc_minutes is None else conc_minutes
        all_ts = sorted({a["ts"] for a in cluster})
        if not all_ts:
            return None
        t_start = all_ts[TELECOM_START_IDX] if TELECOM_START_IDX < len(all_ts) else all_ts[-1]
        t_window = t_start + cm * 60
        counts, earliest = Counter(), {}
        entity_attrs = defaultdict(Counter)
        entity_type = {}
        for a in cluster:
            if a["ts"] > t_window:
                continue
            ent = a["entity"]
            counts[ent] += 1
            earliest[ent] = min(earliest.get(ent, np.inf), a["ts"])
            entity_attrs[ent][a["attribute"]] += 1
            entity_type[ent] = _telecom_component_type(ent)
        candidates = {e for e, c in counts.items() if c >= TELECOM_THRESHOLD}
        if not candidates:
            candidates = {e for e, c in counts.items() if c >= TELECOM_FALLBACK}
        if not candidates:
            return None
        G = self.topology
        rows = []
        for ent in sorted(candidates):
            if ent in G.nodes:
                in_d, out_d = G.in_degree(ent), G.out_degree(ent)
                try:
                    reach = len(nx.descendants(G, ent))
                except Exception:
                    reach = 0
            else:
                in_d = out_d = reach = 0
            rows.append({"entity": ent, "count": counts[ent],
                         "earliest_ts": earliest.get(ent),
                         "in_degree": in_d, "out_degree": out_d, "reachable": reach,
                         "component_type": entity_type[ent],
                         "attrs": dict(entity_attrs.get(ent, {}))})
        df = pd.DataFrame(rows).dropna(subset=["earliest_ts"])
        if df.empty:
            return None
        t_min, t_max = df["earliest_ts"].min(), df["earliest_ts"].max()
        df["time_score"] = 1.0 if t_min == t_max else (t_max - df["earliest_ts"]) / (t_max - t_min)
        max_in = df["in_degree"].max() or 1
        max_out = df["out_degree"].max() or 1
        max_reach = df["reachable"].max() or 1
        # NOTE: in-degree is NOT reversed in the Telecom script (code as run);
        # IN_DEGREE_FLIP inverts it (upstream preferred) for the ablation.
        df["topology_score"] = ((1 - df["in_degree"] / max_in if IN_DEGREE_FLIP else df["in_degree"] / max_in)
                                + df["out_degree"] / max_out
                                + df["reachable"] / max_reach) / 3
        max_count = df["count"].max() or 1
        df["count_score"] = df["count"] / max_count
        df["component_weight"] = df["component_type"].map(TELECOM_COMPONENT_WEIGHTS).fillna(0.5)
        df["final_score"] = (TELECOM_WEIGHTS["time"] * df["time_score"]
                             + TELECOM_WEIGHTS["topo"] * df["topology_score"]
                             + TELECOM_WEIGHTS["count"] * df["count_score"]) * df["component_weight"]
        return df.sort_values("final_score", ascending=False, kind="mergesort").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Market scorer (15.Market_cluster_window_analyze_anomalies_3.3.py)
# ---------------------------------------------------------------------------
MARKET_WEIGHTS = {"time": 0.1, "topo": 0.8, "count": 0.1}
MARKET_CONC_MINUTES = 5
MARKET_START_IDX = 0
MARKET_THRESHOLD = 3
MARKET_FALLBACK = 1

_MARKET_RE_NODE_POD = re.compile(r"^node-\d+\.(.*)$")
_MARKET_RE_SERVICE_PORT = re.compile(r"^([a-zA-Z0-9]+?)(?:2)?\.ts:\d+$")
_MARKET_RE_ISTIO = re.compile(r"^istio-[a-zA-Z]+gateway.*$")
_MARKET_RE_SUFFIX = re.compile(r"^([a-zA-Z]+?)(?:2)?(-\d+)?$")

_MARKET_CALLS = [
    ("frontend", "adservice"), ("frontend", "cartservice"),
    ("frontend", "checkoutservice"), ("frontend", "currencyservice"),
    ("frontend", "recommendationservice"), ("frontend", "productcatalogservice"),
    ("frontend", "shippingservice"), ("checkoutservice", "cartservice"),
    ("checkoutservice", "currencyservice"), ("checkoutservice", "emailservice"),
    ("checkoutservice", "paymentservice"), ("checkoutservice", "productcatalogservice"),
    ("checkoutservice", "shippingservice"), ("recommendationservice", "productcatalogservice"),
]
_MARKET_SERVICES = ["frontend", "adservice", "cartservice", "checkoutservice",
                    "currencyservice", "recommendationservice", "productcatalogservice",
                    "shippingservice", "emailservice", "paymentservice"]


def market_clean_entity(entity):
    """Entity-name cleaning of the original Market script."""
    if not isinstance(entity, str):
        return str(entity) if entity is not None else ""
    m = _MARKET_RE_NODE_POD.match(entity)
    if m:
        cleaned = m.group(1)
        sm = _MARKET_RE_SUFFIX.match(cleaned)
        return sm.group(1) if sm else cleaned
    m = _MARKET_RE_SERVICE_PORT.match(entity)
    if m:
        return m.group(1)
    if _MARKET_RE_ISTIO.match(entity):
        parts = entity.split("-")
        return parts[0] + "-" + parts[1]
    sm = _MARKET_RE_SUFFIX.match(entity)
    if sm:
        return sm.group(1)
    return entity


class MarketScorer:
    def __init__(self):
        edges = []
        for caller, callee in _MARKET_CALLS:
            edges.append((caller, callee))
            edges.append((callee, caller))  # bidirectional
        for svc in _MARKET_SERVICES:
            for suf in ["-0", "-1", "-2", "2-0"]:
                edges.append((svc, f"{svc}{suf}"))
                edges.append((f"{svc}{suf}", svc))
        for gw in ["istio-egressgateway", "istio-ingressgateway"]:
            edges.append(("frontend", gw))
            edges.append((gw, "frontend"))
        self.base_edges = edges

    def _build_topology(self, anomalies):
        G = nx.DiGraph()
        G.add_edges_from(self.base_edges)
        for a in anomalies:
            if "->" in a["entity"]:
                s, t = a["entity"].split("->")
                s_clean, t_clean = market_clean_entity(s), market_clean_entity(t)
                if not G.has_edge(s_clean, t_clean):
                    G.add_edge(s_clean, t_clean)
                if not G.has_edge(s, t):
                    G.add_edge(s, t)
        return G

    def score_cluster(self, cluster, conc_minutes=None):
        cm = MARKET_CONC_MINUTES if conc_minutes is None else conc_minutes
        all_ts = sorted({a["ts"] for a in cluster})
        if not all_ts:
            return None
        t_start = all_ts[MARKET_START_IDX] if MARKET_START_IDX < len(all_ts) else all_ts[-1]
        t_window = t_start + cm * 60
        counts, earliest = Counter(), {}
        entity_attrs = defaultdict(Counter)
        for a in cluster:
            if a["ts"] > t_window:
                continue
            ent = a["entity"]
            if "->" in ent:
                s, t = ent.split("->")
                for e in (s, t):
                    counts[e] += 1
                    earliest[e] = min(earliest.get(e, np.inf), a["ts"])
                    entity_attrs[e][a["attribute"]] += 1
            else:
                counts[ent] += 1
                earliest[ent] = min(earliest.get(ent, np.inf), a["ts"])
                entity_attrs[ent][a["attribute"]] += 1
        candidates = {e for e, c in counts.items() if c >= MARKET_THRESHOLD}
        if not candidates:
            candidates = {e for e, c in counts.items() if c >= MARKET_FALLBACK}
        if not candidates:
            return None
        G = self._build_topology(cluster)
        cand_clean = {e: market_clean_entity(e) for e in candidates}

        def reachable(ent):
            cleaned = cand_clean[ent]
            if cleaned in G.nodes:
                try:
                    desc = nx.descendants(G, cleaned)
                    return len([n for n in desc
                                if n in candidates or n in set(cand_clean.values())]) + 1
                except Exception:
                    pass
            if ent in G.nodes:
                try:
                    desc = nx.descendants(G, ent)
                    return len([n for n in desc if n in candidates]) + 1
                except Exception:
                    pass
            return 0

        def degree(ent, kind):
            cleaned = cand_clean[ent]
            if cleaned in G.nodes:
                return G.in_degree(cleaned) if kind == "in" else G.out_degree(cleaned)
            if ent in G.nodes:
                return G.in_degree(ent) if kind == "in" else G.out_degree(ent)
            return 0

        rows = [{"entity": ent, "count": counts[ent], "earliest_ts": earliest.get(ent),
                 "in_degree": degree(ent, "in"), "out_degree": degree(ent, "out"),
                 "reachable": reachable(ent), "attrs": dict(entity_attrs.get(ent, {}))}
                for ent in sorted(candidates)]
        df = pd.DataFrame(rows).dropna(subset=["earliest_ts"])
        if df.empty:
            return None
        t_min, t_max = df["earliest_ts"].min(), df["earliest_ts"].max()
        df["time_score"] = 1.0 if t_min == t_max else (t_max - df["earliest_ts"]) / (t_max - t_min)
        max_in = df["in_degree"].max() or 1
        max_out = df["out_degree"].max() or 1
        max_reach = df["reachable"].max() or 1
        df["topology_score"] = ((df["in_degree"] / max_in if IN_DEGREE_FLIP else 1 - df["in_degree"] / max_in)
                                + df["out_degree"] / max_out
                                + df["reachable"] / max_reach) / 3
        max_count = df["count"].max() or 1
        df["count_score"] = df["count"] / max_count
        df["component_weight"] = 1.0
        df["final_score"] = (MARKET_WEIGHTS["time"] * df["time_score"]
                             + MARKET_WEIGHTS["topo"] * df["topology_score"]
                             + MARKET_WEIGHTS["count"] * df["count_score"])
        return df.sort_values("final_score", ascending=False, kind="mergesort").reset_index(drop=True)


SCORERS = {"Bank": BankScorer, "Telecom": TelecomScorer,
           "Market-1": MarketScorer, "Market-2": MarketScorer}


# ---------------------------------------------------------------------------
# entity -> candidate-inventory alignment
# ---------------------------------------------------------------------------
def map_to_inventory(raw_entity, inventory):
    """Map a raw scorer entity name to the official candidate name, or None."""
    inv = set(inventory)
    e = raw_entity.strip()
    if e in inv:
        return e
    # trace/mesh targets: "os_021:OSB,null,osb_001" -> "os_021";
    # "checkoutservice-0:hipstershop.CurrencyService/Convert" -> "checkoutservice-0"
    if ":" in e:
        head = e.split(":", 1)[0]
        if head in inv:
            return head
    # container cmdb: "node-6.cartservice2-0" -> pod part preferred, else node
    m = _MARKET_RE_NODE_POD.match(e)
    if m:
        pod = m.group(1)
        if pod in inv:
            return pod
        node = e.split(".", 1)[0]
        if node in inv:
            return node
    # istio mesh: "adservice-0.destination.frontend.adservice" -> "adservice-0"
    if ".destination." in e:
        src = e.split(".destination.", 1)[0]
        if src in inv:
            return src
    # istio mesh source form: "frontend-0.source.frontend.jaeger-collector" -> "frontend-0"
    if ".source." in e:
        src = e.split(".source.", 1)[0]
        if src in inv:
            return src
    # runtime metrics: "adservice.ts:8088" / "adservice2.ts:8088" -> "adservice"
    m = _MARKET_RE_SERVICE_PORT.match(e)
    if m and m.group(1) in inv:
        return m.group(1)
    # service metric suffixes: "adservice-grpc" -> "adservice"
    for suf in ("-grpc", "-http", "-external"):
        if e.endswith(suf) and e[: -len(suf)] in inv:
            return e[: -len(suf)]
    return None


# ---------------------------------------------------------------------------
# attribute -> record.csv reason vocabulary (rule-based fault type answer)
# ---------------------------------------------------------------------------
def _kw_rule(attr, rules):
    a = attr.lower()
    for kw, reason in rules:
        if kw in a:
            return reason
    return None


BANK_REASON_RULES = [
    ("heapmemory", "JVM Out of Memory (OOM) Heap"),
    ("patternid_", "JVM Out of Memory (OOM) Heap"),  # Bank fault-window logs are dominantly OOM/GC
    ("jvm", "high JVM CPU load"),
    ("cpu", "high CPU usage"),
    ("fsavailablespace", "high disk space usage"),
    ("space", "high disk space usage"),
    ("dsk", "high disk I/O read usage"),
    ("disk", "high disk I/O read usage"),
    ("netinerr", "network packet loss"),
    ("netouterr", "network packet loss"),
    ("packet", "network packet loss"),
    ("mrt", "network latency"),
    ("duration", "network latency"),
    ("latency", "network latency"),
    ("mem", "high memory usage"),
]
TELECOM_REASON_RULES = [
    ("cpu", "CPU fault"),
    ("processor", "CPU fault"),
    ("proc_", "CPU fault"),
    ("sess_connect", "db connection limit"),
    ("connection", "db connection limit"),
    ("login", "db connection limit"),
    ("close", "db close"),
    ("shutdown", "db close"),
    ("status", "db close"),
    ("packet", "network loss"),
    ("loss", "network loss"),
    ("error", "network loss"),
    ("trace_", "network delay"),
    ("latency", "network delay"),
    ("delay", "network delay"),
    ("duration", "network delay"),
    ("queue", "network delay"),
    ("response", "network delay"),
]


def _market_reason(attr, entity):
    a = attr.lower()
    is_node = bool(re.match(r"^node-\d+$", entity))
    rules = [
        ("retrans", "container network packet retransmission"),
        ("corrupt", "container network packet corruption"),
        ("dropped", "container packet loss"),
        ("packet", "container packet loss"),
        ("latency", "container network latency"),
        ("kill", "container process termination"),
        ("term", "container process termination"),
        ("iowait", "node disk read I/O consumption"),
        ("rd", None),  # resolved below
        ("read", None),
        ("wr", None),
        ("write", None),
        ("disk", "node disk space consumption"),
        ("space", "node disk space consumption"),
        ("cpu", "node CPU load" if is_node else "container CPU load"),
        ("mem", "node memory consumption" if is_node else "container memory load"),
        ("duration", "container network latency"),
        ("mrt", "container network latency"),
    ]
    for kw, reason in rules:
        if kw in a:
            if reason is None:
                if kw in ("rd", "read"):
                    return "node disk read I/O consumption" if is_node else "container read I/O load"
                return "node disk write I/O consumption" if is_node else "container write I/O load"
            return reason
    return None


def predict_reason(dataset, attrs_counter, entity, modal_reason):
    """Map an entity's dominant anomaly attributes to the reason vocabulary."""
    for attr, _cnt in Counter(attrs_counter).most_common():
        if dataset == "Bank":
            r = _kw_rule(attr, BANK_REASON_RULES)
        elif dataset == "Telecom":
            r = _kw_rule(attr, TELECOM_REASON_RULES)
        else:
            r = _market_reason(attr, entity)
        if r:
            return r
    return modal_reason


# ---------------------------------------------------------------------------
# query-level scoring
# ---------------------------------------------------------------------------
_SCORER_INSTANCES = {}


def get_scorer(dataset):
    if dataset not in _SCORER_INSTANCES:
        _SCORER_INSTANCES[dataset] = SCORERS[dataset]()
    return _SCORER_INSTANCES[dataset]


def score_anomalies(dataset, anomalies, eps=DBSCAN_EPS_SECONDS,
                    min_samples=DBSCAN_MIN_SAMPLES, conc_minutes=None):
    """Cluster + score a preloaded anomaly list for one query window.

    eps / min_samples: DBSCAN parameters (paper default 60s / 3).
    conc_minutes: concentration-window length in minutes (the paper's "num";
        None = the dataset's current script value: Bank 4, Telecom 5,
        Market 5).  The analysis-start timestamp index stays fixed per
        dataset (Bank/Telecom: 3rd distinct ts; Market: 1st).

    Returns a dict with:
      n_anomalies, clusters (sizes), primary_size, first_anomaly_ts (of the
      primary cluster), ranked_raw (raw entity ranking after the deterministic
      cross-cluster merge), entity_rows {raw_entity: score-record dict},
      entity_attrs {raw_entity: {attr: count}}.
    """
    clusters, _noise = dbscan_clusters(anomalies, eps=eps, min_samples=min_samples)
    scorer = get_scorer(dataset)
    scored = []
    for cl in clusters:
        df = scorer.score_cluster(cl, conc_minutes=conc_minutes)
        if df is not None and not df.empty:
            scored.append((cl, df))
    # deterministic LLM replacement: dominant cluster (most anomalies) first
    scored.sort(key=lambda t: len(t[0]), reverse=True)
    ranked_raw, entity_rows, entity_attrs = [], {}, {}
    for cl, df in scored:
        for _, row in df.iterrows():
            ent = row["entity"]
            if ent in entity_rows:
                continue
            ranked_raw.append(ent)
            entity_rows[ent] = {k: row[k] for k in
                                ("final_score", "time_score", "topology_score",
                                 "count_score", "component_weight", "count",
                                 "earliest_ts")}
            entity_attrs[ent] = row["attrs"]
    first_ts = min((a["ts"] for a in scored[0][0]), default=None) if scored else None
    return {
        "n_anomalies": len(anomalies),
        "clusters": [len(cl) for cl, _ in scored],
        "primary_size": len(scored[0][0]) if scored else 0,
        "first_anomaly_ts": first_ts,
        "ranked_raw": ranked_raw,
        "entity_rows": entity_rows,
        "entity_attrs": entity_attrs,
    }


def score_query(dataset, ws, we, **kw):
    """Load the window's cached anomaly records and score them
    (see score_anomalies for the keyword parameters)."""
    anomalies = LOADERS[dataset](ws, we)
    return score_anomalies(dataset, anomalies, **kw)


def rank_candidates(dataset, ws, we, inventory, anomalies=None, **kw):
    """score_query + inventory alignment -> candidate-level result."""
    res = score_query(dataset, ws, we, **kw) if anomalies is None \
        else score_anomalies(dataset, anomalies, **kw)
    ranked, seen = [], set()
    raw2cand = {}
    for raw in res["ranked_raw"]:
        cand = map_to_inventory(raw, inventory)
        raw2cand[raw] = cand
        if cand is None or cand in seen:
            continue
        seen.add(cand)
        ranked.append(cand)
    # candidate-level score records (via their raw representative)
    cand_rows = {}
    cand_attrs = {}
    for raw, cand in raw2cand.items():
        if cand is not None and cand not in cand_rows:
            cand_rows[cand] = res["entity_rows"][raw]
            cand_attrs[cand] = res["entity_attrs"][raw]
    res.update({"ranked_entities": ranked, "candidate_rows": cand_rows,
                "candidate_attrs": cand_attrs, "raw2cand": raw2cand})
    return res
