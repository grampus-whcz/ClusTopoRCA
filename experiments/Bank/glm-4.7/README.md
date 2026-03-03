# _all_RAG_
public corpus + private corpus + RAG k1

# _all_RAG_k4_
public corpus + private corpus + RAG k4

# _no_RAG_c3_
no RAG + clustering DBSCAN min_samples=3

# _no_RAG_c3_log_context_
no RAG + clustering DBSCAN min_samples=3 + log context (old log template)

# _no_RAG_c3_log_template_new_context_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method

# _no_RAG_c3_log_template_new_context_back_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage)

# _no_RAG_c3_log_template_new_context_back_llm_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context

# _no_RAG_c3_log_template_new_context_back_llm_tune1_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context + RCA prompt tuning + Bank_cluster_window_analyze_anomalies_2.3.py

# _no_RAG_c3_log_template_new_context_back_llm_tune2_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context + RCA prompt tuning + Bank_cluster_window_analyze_anomalies.py

# _no_RAG_c3_log_template_new_context_back_llm_tune3_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context + RCA prompt tuning + Bank_cluster_window_analyze_anomalies.py + prompt tuning

# _no_RAG_c3_log_template_new_context_back_llm_tune4_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context + RCA prompt tuning + Bank_cluster_window_analyze_anomalies.py + prompt tuning + log context only for score tuning

# _no_RAG_c3_log_template_new_context_back_llm_tune5_
no RAG + clustering DBSCAN min_samples=3 + log context (new log template) + new log method + put log content after clustering (directly in the final RCA stage) + use llm to generate log context + RCA prompt tuning + Bank_cluster_window_analyze_anomalies.py + prompt tuning + log context only for score tuning + cluster prompt tuning

# _no_RAG_c3_log_template_new_context_back_llm_tune6_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 0 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune7_
## best
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 4
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.3
WEIGHT_TOPOLOGY = 0.4
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 2   -->

# _no_RAG_c3_log_template_new_context_back_llm_tune8_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 5
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.2
WEIGHT_TOPOLOGY = 0.5
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 1   -->

# _no_RAG_c3_log_template_new_context_back_llm_tune9_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 3
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 3 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune10_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 3
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 0 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune11_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 2   -->

# _no_RAG_c3_log_template_new_context_back_llm_tune12_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 4
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 0 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune13_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 4
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 1 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune14_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.3
WEIGHT_TOPOLOGY = 0.4
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 0 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune15_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 3
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.5
WEIGHT_TOPOLOGY = 0.2
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 0 -->

# _no_RAG_c3_log_template_new_context_back_llm_tune16_
no RAG + clustering DBSCAN min_samples=3 + dependency analysis (topology/root cause scoring) logic after clustering

<!-- CONCENTRATION_WINDOW_MINUTES = 4
ANOMALY_THRESHOLD = 2
FALLBACK_THRESHOLD = 1
WEIGHT_TIME = 0.4
WEIGHT_TOPOLOGY = 0.3
WEIGHT_COUNT = 0.3
ANALYSIS_START_TIMESTAMP_INDEX = 2   -->