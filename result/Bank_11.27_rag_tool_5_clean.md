nohup: ignoring input
2025-11-27 12:23:45.733 | INFO     | __main__:main:72 - Using dataset: Bank
2025-11-27 12:23:45.733 | INFO     | __main__:main:73 - Using model: Qwen3-235B-A22B-Instruct-2507
2025-11-27 12:23:45.733 | INFO     | __main__:main:74 - Using API_BASE: https://api-inference.modelscope.cn/v1
2025-11-27 12:23:45.797 | INFO     | __main__:main:105 - 
################################################################################
2025-11-27_12-23-36_#11-0: task_1
################################################################################
2025-11-27 12:23:45.797 | INFO     | rca.baseline.rag_tool_multicandidate_agent.rca_agent:run:11 - Objective: Within the time range of March 7, 2021, from 16:00 to 16:30, there were two failures detected in the system. However, the exact time of the root cause occurrence for these failures is currently unknown. Please determine the root cause occurrence datetime.
2025-11-27 12:23:49.016 | INFO     | rca.baseline.rag_tool_multicandidate_agent.controller:control_loop:112 - --------------------------------------------------------------------------------
### Step[1]
Analysis: None
Instruction: List all available telemetry data directories under dataset/Bank/telemetry/ to confirm the existence of the directory for March 7, 2021, and verify its contents.
--------------------------------------------------------------------------------
2025-11-27 12:23:49.705 | INFO     | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:17 - Start execution via tool agent
2025-11-27 12:23:56.669 | INFO     | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:78 - LLM Tool Call Response:
{
  "pipeline_type": "all",
  "date_offline": "2021_03_05",
  "date_online": "2021_03_07",
  "start_ts": 1615104000,
  "end_ts": 1615105800,
  "method": "TranAD",
  "output_folder_name": "1127",
  "output_suffix": "1600_1630"
}
2025-11-27 12:57:11.101 | INFO     | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:89 - Tool Execution Result:

============================================================
[Bank_metric_container] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_container_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed metric container Anomaly Report (Beijing Time = UTC+8):
================================================================================

Entity: IG01
  - Attribute 'OSLinux-OSLinux_NETWORK_NETWORK_TCP-CLOSE-WAIT': 1 anomalies at timestamps:
      1615104060 (2021-03-07 16:01:00 CST)
  - Attribute 'OSLinux-OSLinux_PROCESS_PROCESS_PROCNoZombies': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)
  - Attribute 'OSLinux-OSLinux_PROCESS_zabbix_PROCPPCount': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)
  - Attribute 'OSLinux-OSLinux_ZABBIX_Host_Uptime': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)

Entity: IG02
  - Attribute 'JVM-Memory_7778_JVM_Memory_NoHeapMemoryUsed': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'OSLinux-OSLinux_LOCALDISK_LOCALDISK-sda_DSKRTps': 2 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST), 1615104120 (2021-03-07 16:02:00 CST)
...

[Bank_metric_app] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_app_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed metric app Anomaly Report (Beijing Time = UTC+8):
================================================================================

Entity: ServiceTest1
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest10
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 2 anomalies at timestamps:
      1615105740 (2021-03-07 16:29:00 CST), 1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest11
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 2 anomalies at timestamps:
      1615105740 (2021-03-07 16:29:00 CST), 1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest2
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 1 anomalies at timestamps:
      ...

[Bank_trace] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_trace_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed Trace Anomaly Report (Beijing Time = UTC+8):
================================================================================

Edge: IG01->IG01
  - Attribute 'duration': 1 anomalies at timestamps:
      1615105738 (2021-03-07 16:28:58 CST)

Edge: IG02->IG02
  - Attribute 'duration': 1 anomalies at timestamps:
      1615105738 (2021-03-07 16:28:58 CST)

Edge: MG01->MG01
  - Attribute 'frequency': 2 anomalies at timestamps:
      1615104598 (2021-03-07 16:09:58 CST), 1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->dockerA1
  - Attribute 'duration': 1 anomalies at timestamps:
      1615104658 (2021-03-07 16:10:58 CST)
  - Attribute 'frequency': 2 anomalies at timestamps:
      1615104598 (2021-03-07 16:09:58 CST), 1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->dockerA2
  - Attribute 'duration': 1 anomalies at timestamps:
      1615104658 (2021-03-07 16:10:58 CST)
  - Attribute 'frequency': 1 anomalies at timestamps:
      1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->...

[Bank_log] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_log_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed Log Anomaly Report (Beijing Time = UTC+8):
================================================================================

Pod: IG01
  - Pattern ID 2 (2 anomalies):
      Template: <:NUM:>.<:NUM:>: [CMS-concurrent-mark: <:NUM:>.<:NUM:>/<:NUM:>.<:NUM:> secs] [Times: user=<:NUM:>.<:NUM:> sys=<:NUM:>.<:NUM:>, real=<:NUM:>.<:NUM:> secs]
      1615104300 (2021-03-07 16:05:00 CST), 1615104360 (2021-03-07 16:06:00 CST)
  - Pattern ID 6 (1 anomalies):
      Template: <:NUM:>.<:NUM:>: [GC (CMS Initial Mark) [<:NUM:> CMS-initial-mark: <:*:> <:*:> <:NUM:>.<:NUM:> secs] [Times: user=<:NUM:>.<:NUM:> sys=<:NUM:>.<:NUM:>, real=<:NUM:>.<:NUM:> secs]
      1615104120 (2021-03-07 16:02:00 CST)
  - Pattern ID 7 (1 anomalies):
      Template: <:NUM:>.<:NUM:>: [GC (CMS Final Remark) [YG occupancy: <:NUM:> K (<:NUM:> K)]<:NUM:>-<:NUM:>-04T00:<:NUM:>:<:NUM:>.<:NUM:>+<:NUM:>: <:NUM:>.<:NUM:>: [Rescan (parallel) , <:NUM:>.<:NUM:> secs]<:NUM:>-< ...
      1615105320 (2021-03-07 16:22:00 CST)
  - P...

[Bank_cluster_window] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_cluster_window_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:
🔍 Anomaly Clustering Report for 2021_03_07 1600_1630
🔍 The number of clusters are 2021_03_07 1600_1630
================================================================================

🔍 The number of clusters are 2
========================================

🚨 Cluster #1
   Time Span: 2021-03-07 16:00:00 CST → 2021-03-07 16:15:00 CST (Δ = 900 sec)
   Total Anomalies: 600
   🔑 Keywords: GC, Error/Failure

   📝 Log Anomalies:
     • Entity: IG01 | Attribute: PatternID_10
       Timestamps: 1615104660 (2021-03-07 16:11:00 CST)
     • Entity: IG01 | Attribute: PatternID_107
       Timestamps: 1615104300 (2021-03-07 16:05:00 CST)
     • Entity: IG01 | Attribute: PatternID_108
       Timestamps: 1615104120 (2021-03-07 16:02:00 CST)
     • Entity: IG01 | Attribute: PatternID_12
       Timestamps: 1615104240 (2021-03-07 16:04:00 CST)
     • Entity: IG01 | Attribute: PatternID_121
       Timestamps: 1615104120 (2021-03-07 16:02:00 CST)
     • Entity: IG01 | Attribute: PatternID_125
       Timest...

============================================================

2025-11-27 12:57:11.105 | WARNING  | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:100 - Report file not found: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_container_anomaly_report_2021_03_07_1600_1630.txt
2025-11-27 12:57:11.108 | WARNING  | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:100 - Report file not found: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_app_anomaly_report_2021_03_07_1600_1630.txt
2025-11-27 12:57:11.111 | WARNING  | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:100 - Report file not found: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_trace_anomaly_report_2021_03_07_1600_1630.txt
report_paths: ['/root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_cluster_window_anomaly_report_2021_03_07_1600_1630.txt']
2025-11-27 12:57:11.111 | WARNING  | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:100 - Report file not found: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_log_anomaly_report_2021_03_07_1600_1630.txt
2025-11-27 12:57:33.982 | INFO     | rca.baseline.rag_tool_multicandidate_agent.executor:execute_act:135 - Final Answer:
{
  "Cluster 1": "Between 16:00 and 16:15 CST, a major anomaly cluster centered on IG01 showed repeated garbage collection (GC) and system errors. Multiple log patterns (e.g., CMS GC events) occurred at IG01, indicating JVM stress. Simultaneously, Redis02, MG01, MG02, and database servers (Mysql01/02) exhibited abnormal metrics including high CPU, memory pressure, disk I/O, TCP connection issues, and container resource spikes. Tomcat instances (Tomcat01–04) reported memory and session anomalies. Trace data showed increased call frequency and latency between microservices (e.g., MG01/MG02 to Docker containers), suggesting cascading failures likely triggered by JVM GC events on IG01 affecting downstream systems.",
  "Cluster 2": "Between 16:18 and 16:30 CST, a follow-up anomaly cluster emerged, primarily affecting Redis02, Mysql02, and Docker containers. Redis02 showed container memory and CPU fluctuations, JVM memory anomalies, and MySQL-related metric spikes (e.g., row locks, buffer pool activity), indicating ongoing database stress. Mysql01/02 had disk and connection anomalies. Tomcat03 and Tomcat04 reported CPU and network issues. Trace data revealed abnormal call durations and frequencies from unknown sources to IG02, MG01, and Docker services at 16:24–16:25, suggesting residual system instability or failed recovery attempts after the earlier GC event, possibly involving container orchestration or retry loops."
}
/root/shared-nvme/work/agent/OpenRCA/rca/baseline/rag_agent/rag_retriever_new_data.py:87: LangChainDeprecationWarning: The class `HuggingFaceEmbeddings` was deprecated in LangChain 0.2.2 and will be removed in 1.0. An updated version of the class exists in the :class:`~langchain-huggingface package and should be used instead. To use it run `pip install -U :class:`~langchain-huggingface` and import as `from :class:`~langchain_huggingface import HuggingFaceEmbeddings``.
  self.embedding_model = HuggingFaceEmbeddings(
/root/shared-nvme/.conda/envs/faiss-env/lib/python3.10/site-packages/transformers/utils/hub.py:111: FutureWarning: Using `TRANSFORMERS_CACHE` is deprecated and will be removed in v5 of Transformers. Use `HF_HOME` instead.
  warnings.warn(
Initializing Postmortem RAG Retriever...
Building new FAISS index from postmortem JSONL files...
FAISS index saved to faiss_index_postmortem
2025-11-27 12:57:49.559 | INFO     | rca.baseline.rag_tool_multicandidate_agent.controller:control_loop:183 - --------------------------------------------------------------------------------
Step[1]
### Observation:
{
  "Cluster 1": "Between 16:00 and 16:15 CST, a major anomaly cluster centered on IG01 showed repeated garbage collection (GC) and system errors. Multiple log patterns (e.g., CMS GC events) occurred at IG01, indicating JVM stress. Simultaneously, Redis02, MG01, MG02, and database servers (Mysql01/02) exhibited abnormal metrics including high CPU, memory pressure, disk I/O, TCP connection issues, and container resource spikes. Tomcat instances (Tomcat01–04) reported memory and session anomalies. Trace data showed increased call frequency and latency between microservices (e.g., MG01/MG02 to Docker containers), suggesting cascading failures likely triggered by JVM GC events on IG01 affecting downstream systems.",
  "Cluster 2": "Between 16:18 and 16:30 CST, a follow-up anomaly cluster emerged, primarily affecting Redis02, Mysql02, and Docker containers. Redis02 showed container memory and CPU fluctuations, JVM memory anomalies, and MySQL-related metric spikes (e.g., row locks, buffer pool activity), indicating ongoing database stress. Mysql01/02 had disk and connection anomalies. Tomcat03 and Tomcat04 reported CPU and network issues. Trace data revealed abnormal call durations and frequencies from unknown sources to IG02, MG01, and Docker services at 16:24–16:25, suggesting residual system instability or failed recovery attempts after the earlier GC event, possibly involving container orchestration or retry loops."
}
The original execution output of the tool is also provided below for reference:

============================================================
[Bank_metric_container] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_container_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed metric container Anomaly Report (Beijing Time = UTC+8):
================================================================================

Entity: IG01
  - Attribute 'OSLinux-OSLinux_NETWORK_NETWORK_TCP-CLOSE-WAIT': 1 anomalies at timestamps:
      1615104060 (2021-03-07 16:01:00 CST)
  - Attribute 'OSLinux-OSLinux_PROCESS_PROCESS_PROCNoZombies': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)
  - Attribute 'OSLinux-OSLinux_PROCESS_zabbix_PROCPPCount': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)
  - Attribute 'OSLinux-OSLinux_ZABBIX_Host_Uptime': 1 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST)

Entity: IG02
  - Attribute 'JVM-Memory_7778_JVM_Memory_NoHeapMemoryUsed': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'OSLinux-OSLinux_LOCALDISK_LOCALDISK-sda_DSKRTps': 2 anomalies at timestamps:
      1615104000 (2021-03-07 16:00:00 CST), 1615104120 (2021-03-07 16:02:00 CST)
...

[Bank_metric_app] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_metric_app_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed metric app Anomaly Report (Beijing Time = UTC+8):
================================================================================

Entity: ServiceTest1
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest10
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 2 anomalies at timestamps:
      1615105740 (2021-03-07 16:29:00 CST), 1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest11
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 2 anomalies at timestamps:
      1615105740 (2021-03-07 16:29:00 CST), 1615105800 (2021-03-07 16:30:00 CST)

Entity: ServiceTest2
  - Attribute 'cnt': 1 anomalies at timestamps:
      1615105800 (2021-03-07 16:30:00 CST)
  - Attribute 'mrt': 1 anomalies at timestamps:
      ...

[Bank_trace] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_trace_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed Trace Anomaly Report (Beijing Time = UTC+8):
================================================================================

Edge: IG01->IG01
  - Attribute 'duration': 1 anomalies at timestamps:
      1615105738 (2021-03-07 16:28:58 CST)

Edge: IG02->IG02
  - Attribute 'duration': 1 anomalies at timestamps:
      1615105738 (2021-03-07 16:28:58 CST)

Edge: MG01->MG01
  - Attribute 'frequency': 2 anomalies at timestamps:
      1615104598 (2021-03-07 16:09:58 CST), 1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->dockerA1
  - Attribute 'duration': 1 anomalies at timestamps:
      1615104658 (2021-03-07 16:10:58 CST)
  - Attribute 'frequency': 2 anomalies at timestamps:
      1615104598 (2021-03-07 16:09:58 CST), 1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->dockerA2
  - Attribute 'duration': 1 anomalies at timestamps:
      1615104658 (2021-03-07 16:10:58 CST)
  - Attribute 'frequency': 1 anomalies at timestamps:
      1615104718 (2021-03-07 16:11:58 CST)

Edge: MG01->...

[Bank_log] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_log_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:

📝 Detailed Log Anomaly Report (Beijing Time = UTC+8):
================================================================================

Pod: IG01
  - Pattern ID 2 (2 anomalies):
      Template: <:NUM:>.<:NUM:>: [CMS-concurrent-mark: <:NUM:>.<:NUM:>/<:NUM:>.<:NUM:> secs] [Times: user=<:NUM:>.<:NUM:> sys=<:NUM:>.<:NUM:>, real=<:NUM:>.<:NUM:> secs]
      1615104300 (2021-03-07 16:05:00 CST), 1615104360 (2021-03-07 16:06:00 CST)
  - Pattern ID 6 (1 anomalies):
      Template: <:NUM:>.<:NUM:>: [GC (CMS Initial Mark) [<:NUM:> CMS-initial-mark: <:*:> <:*:> <:NUM:>.<:NUM:> secs] [Times: user=<:NUM:>.<:NUM:> sys=<:NUM:>.<:NUM:>, real=<:NUM:>.<:NUM:> secs]
      1615104120 (2021-03-07 16:02:00 CST)
  - Pattern ID 7 (1 anomalies):
      Template: <:NUM:>.<:NUM:>: [GC (CMS Final Remark) [YG occupancy: <:NUM:> K (<:NUM:> K)]<:NUM:>-<:NUM:>-04T00:<:NUM:>:<:NUM:>.<:NUM:>+<:NUM:>: <:NUM:>.<:NUM:>: [Rescan (parallel) , <:NUM:>.<:NUM:> secs]<:NUM:>-< ...
      1615105320 (2021-03-07 16:22:00 CST)
  - P...

[Bank_cluster_window] Execution successful.
Report saved to: /root/shared-nvme/work/timeSeries/OmniTransfer_new/1127/Bank_cluster_window_anomaly_report_2021_03_07_1600_1630.txt
Report content preview:
🔍 Anomaly Clustering Report for 2021_03_07 1600_1630
🔍 The number of clusters are 2021_03_07 1600_1630
================================================================================

🔍 The number of clusters are 2
========================================

🚨 Cluster #1
   Time Span: 2021-03-07 16:00:00 CST → 2021-03-07 16:15:00 CST (Δ = 900 sec)
   Total Anomalies: 600
   🔑 Keywords: GC, Error/Failure

   📝 Log Anomalies:
     • Entity: IG01 | Attribute: PatternID_10
       Timestamps: 1615104660 (2021-03-07 16:11:00 CST)
     • Entity: IG01 | Attribute: PatternID_107
       Timestamps: 1615104300 (2021-03-07 16:05:00 CST)
     • Entity: IG01 | Attribute: PatternID_108
       Timestamps: 1615104120 (2021-03-07 16:02:00 CST)
     • Entity: IG01 | Attribute: PatternID_12
       Timestamps: 1615104240 (2021-03-07 16:04:00 CST)
     • Entity: IG01 | Attribute: PatternID_121
       Timestamps: 1615104120 (2021-03-07 16:02:00 CST)
     • Entity: IG01 | Attribute: PatternID_125
       Timest...

============================================================


--------------------------------------------------------------------------------
2025-11-27 12:57:49.559 | WARNING  | rca.baseline.rag_tool_multicandidate_agent.controller:control_loop:198 - Max steps reached. Please check the history.
2025-11-27 12:58:35.928 | INFO     | rca.baseline.rag_tool_multicandidate_agent.rca_agent:run:13 - Result: {
    "1": {
        "root cause occurrence datetime": "2021-03-07 16:00:15"
    },
    "2": {
        "root cause occurrence datetime": "2021-03-07 16:01:30"
    }
}
2025-11-27 12:58:35.945 | INFO     | __main__:main:124 - Trajectory has been saved to test/monitor/Bank/agent-rca-Qwen3-235B-A22B-Instruct-2507/2025-11-27_12-23-36/trajectory/2025-11-27_12-23-36_#11-0.ipynb
2025-11-27 12:58:35.946 | INFO     | __main__:main:128 - Prompt has been saved to test/monitor/Bank/agent-rca-Qwen3-235B-A22B-Instruct-2507/2025-11-27_12-23-36/prompt/2025-11-27_12-23-36_#11-0.json
2025-11-27 12:58:35.964 | INFO     | __main__:main:145 - Prediction: {
    "1": {
        "root cause occurrence datetime": "2021-03-07 16:00:15"
    },
    "2": {
        "root cause occurrence datetime": "2021-03-07 16:01:30"
    }
}
2025-11-27 12:58:35.965 | INFO     | __main__:main:146 - =============================
2025-11-27 12:58:35.965 | INFO     | __main__:main:147 - groundtruth: level: podcomponent: MG01timestamp: 1615104480.0datetime: 2021-03-07 16:08:00reason: network latency
2025-11-27 12:58:35.966 | INFO     | __main__:main:148 - Scoring Points: The 1-th root cause occurrence time is within 1 minutes (i.e., <=1min) of 2021-03-07 16:08:00
The 2-th root cause occurrence time is within 1 minutes (i.e., <=1min) of 2021-03-07 16:29:00

2025-11-27 12:58:35.966 | INFO     | __main__:main:149 - Passed Criteria: []
2025-11-27 12:58:35.966 | INFO     | __main__:main:150 - Failed Criteria: ['2021-03-07 16:08:00', '2021-03-07 16:29:00']
2025-11-27 12:58:35.966 | INFO     | __main__:main:151 - Score: 0.0
