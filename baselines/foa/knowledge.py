"""
SOP and historical-incident knowledge bases for the FoA reproduction.

Follows the paper's data model:
  * SOP      = {"name": ..., "steps": [natural-language steps]}; the name is
               used for retrieval; steps may reference tool calls and by
               convention the last step states that the answer is the
               observations of the former steps (see paper Fig. 3 / Fig. 6).
  * incident = {"manifestation": ..., "type": ...}; the manifestation is used
               for retrieval (match_observation).

SOPs are authored for the OpenRCA fault-type vocabulary (Bank: CPU/memory/
disk IO/disk space/network latency/packet loss/JVM; Telecom: CPU/network/
database; Market: container & node resource and network issues), written in
the style of the paper's examples. The tools referenced by the steps are
implemented in tools_data.py.
"""

SOPS = [
    {"name": "SOP of CPU Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the CPU metrics of all entities are anomalous. (start_time, end_time, metric=\"cpu\")",
         "collect_trace: Collect trace data of the CPU-anomalous entity to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Memory Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the memory metrics of all entities are anomalous. (start_time, end_time, metric=\"memory\")",
         "collect_trace: Collect trace data of the memory-anomalous entity to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Disk IO Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the disk IO / disk usage metrics of all entities are anomalous. (start_time, end_time, metric=\"disk\")",
         "collect_trace: Collect trace data of the disk-anomalous entity to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Network Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the network metrics (errors, dropped packets, bandwidth) of all entities are anomalous. (start_time, end_time, metric=\"network\")",
         "collect_trace: Collect trace data of the network-anomalous entity to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Database Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the database session / connection / TPS / response-time metrics of all database services are anomalous. (start_time, end_time, metric=\"database\")",
         "collect_trace: Collect trace data of the anomalous database service to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of JVM Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the JVM heap memory and JVM CPU metrics of all Java services are anomalous. (start_time, end_time, metric=\"jvm\")",
         "collect_trace: Collect trace data of the JVM-anomalous service to investigate further. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Response Time Issue",
     "steps": [
         "whether_is_abnormal_metric: Check if the response time / success rate metrics of the entry services are anomalous. (start_time, end_time, metric=\"latency\")",
         "collect_trace: Collect trace data of the latency-anomalous service to find the slowest downstream calls. (start_time, end_time, entity)",
         "The answer is the observations obtained from former steps."]},
    {"name": "SOP of Pod Issue",
     "steps": [
         "Analyze pod status",
         "Find anomalous pod",
         "Collect trace"]},
]

INCIDENTS = [
    # Bank fault types
    {"manifestation": "CPU usage or CPU utilization of an entity is anomalously high", "type": "high CPU usage"},
    {"manifestation": "memory usage percentage of an entity is anomalously high", "type": "high memory usage"},
    {"manifestation": "disk is busy, disk read IO is anomalously high", "type": "high disk I/O read usage"},
    {"manifestation": "disk space usage of an entity is anomalously high", "type": "high disk space usage"},
    {"manifestation": "network packets are lost, network in/out errors are anomalous", "type": "network packet loss"},
    {"manifestation": "network delay makes response time and duration anomalously high", "type": "network latency"},
    {"manifestation": "JVM heap memory usage is anomalously high, out of memory", "type": "JVM Out of Memory (OOM) Heap"},
    {"manifestation": "JVM CPU load of a Java service is anomalously high", "type": "high JVM CPU load"},
    # Telecom fault types
    {"manifestation": "CPU fault: CPU utilization of a node or docker is anomalously high", "type": "CPU fault"},
    {"manifestation": "network delay: response time and elapsed time are anomalously high", "type": "network delay"},
    {"manifestation": "network loss: network traffic or packets are dropped or lost", "type": "network loss"},
    {"manifestation": "database connection limit reached, session percentage anomalously high", "type": "db connection limit"},
    {"manifestation": "database close: database service is down or closed, calls fail", "type": "db close"},
    # Market fault types (container-level and node-level)
    {"manifestation": "container CPU load: container cpu usage is anomalously high", "type": "container CPU load"},
    {"manifestation": "container read IO load: container filesystem reads are anomalously high", "type": "container read I/O load"},
    {"manifestation": "container network packets are corrupted or dropped", "type": "container network packet corruption"},
    {"manifestation": "container memory consumption is anomalously high", "type": "container memory consumption"},
    {"manifestation": "node CPU consumption is anomalously high", "type": "node CPU consumption"},
    {"manifestation": "node memory consumption is anomalously high", "type": "node memory consumption"},
    {"manifestation": "node disk space consumption is anomalously high", "type": "node disk space consumption"},
    {"manifestation": "node network is anomalous, cannot connect, packet loss", "type": "node network loss"},
    {"manifestation": "process on the node is terminated, service stops responding", "type": "process termination"},
]
