"""
MetricExplorer for the OpenRCA adaptation of mABC.

Same query interface as the original handle/metric_collect.py, but the stats
file location comes from settings (per-dataset directory built by
build_data.py) instead of the hardcoded "data/metric/endpoint_stats.json".
"""

import json
from datetime import datetime, timedelta

from settings import MABC_DATA_DIR

_EMPTY = {'calls': 0, 'success_rate': 0, 'error_rate': 0, 'average_duration': 0, 'timeout_rate': 0}


class MetricExplorer:
    def __init__(self):
        stats_file = f"{MABC_DATA_DIR}/endpoint_stats.json"
        self.aggregated_stats = self.load_data(stats_file)

    def load_data(self, filename):
        with open(filename, 'r') as f:
            return json.load(f)

    def query_endpoint_stats(self, endpoint, time_minute):
        endpoint_data = self.aggregated_stats.get(endpoint, {})
        # accept both "YYYY-MM-DD HH:MM" and "YYYY-MM-DD HH:MM:SS" queries
        if time_minute in endpoint_data:
            return endpoint_data[time_minute]
        for key, val in endpoint_data.items():
            if key.startswith(time_minute):
                return val
        return {}

    def query_endpoint_stats_in_range(self, endpoint, time_minute):
        range_stats = {}
        example_time_minute = datetime.strptime(time_minute, '%Y-%m-%d %H:%M:%S')
        start_time = example_time_minute - timedelta(minutes=15)
        end_time = example_time_minute + timedelta(minutes=5)
        current_time = start_time
        while current_time <= end_time:
            time_minute_str = current_time.strftime('%Y-%m-%d %H:%M:%S')
            if endpoint in self.aggregated_stats:
                range_stats[time_minute_str] = self.aggregated_stats[endpoint].get(time_minute_str, dict(_EMPTY))
            current_time += timedelta(minutes=1)
        return range_stats
