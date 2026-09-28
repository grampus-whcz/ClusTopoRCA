"""
TraceExplorer for the OpenRCA adaptation of mABC.

Same query interface as the original handle/trace_collect.py, with repairs:
  * the original hardcoded an absolute path on the authors' machine
    ("/root/work/ops/data/topology/endpoint_maps.json"); the path now comes
    from settings (per-dataset directory built by build_data.py);
  * ``get_endpoint_downstream(endpoint)`` is implemented in a minute-agnostic
    way (union over minutes) because the tool layer calls it with a single
    argument while the original class required two;
  * ``get_endpoint_upstream`` and ``get_call_chain_for_endpoint`` did not
    exist upstream (the exposed tools therefore always failed); they are
    implemented here over the same endpoint_maps structure.
"""

import json
from datetime import datetime, timedelta

from settings import MABC_DATA_DIR


class TraceExplorer:
    def __init__(self):
        files = f"{MABC_DATA_DIR}/endpoint_maps.json"
        self.endpoint_maps = self.load_data(files)

    def load_data(self, filename):
        with open(filename, 'r') as f:
            return json.load(f)

    def get_endpoint_downstream(self, endpoint, time_minute=None):
        if time_minute is not None:
            t = self.endpoint_maps.get(endpoint, {})
            return t.get(time_minute, [])
        # minute-agnostic: union of downstreams across all minutes
        downstream = set()
        for minute_list in self.endpoint_maps.get(endpoint, {}).values():
            downstream.update(minute_list)
        return sorted(downstream)

    def get_endpoint_downstream_in_range(self, endpoint, time_minute):
        range_stats = {}
        example_time_minute = datetime.strptime(time_minute, '%Y-%m-%d %H:%M:%S')
        start_time = example_time_minute - timedelta(minutes=15)
        end_time = example_time_minute + timedelta(minutes=5)
        current_time = start_time
        while current_time <= end_time:
            time_minute_str = current_time.strftime('%Y-%m-%d %H:%M:%S')
            if endpoint in self.endpoint_maps:
                range_stats[time_minute_str] = self.endpoint_maps[endpoint].get(time_minute_str, [])
            current_time += timedelta(minutes=1)
        return range_stats

    def _upstream_map(self):
        # reverse of endpoint_maps: downstream -> {minute: [upstreams]}
        if not hasattr(self, "_upstream"):
            upstream = {}
            for up, minutes in self.endpoint_maps.items():
                for minute, downs in minutes.items():
                    for down in downs:
                        upstream.setdefault(down, {}).setdefault(minute, set()).add(up)
            self._upstream = {k: {m: sorted(v) for m, v in mm.items()}
                              for k, mm in upstream.items()}
        return self._upstream

    def get_endpoint_upstream(self, endpoint, time_minute=None):
        upstream = self._upstream_map()
        if time_minute is not None:
            return upstream.get(endpoint, {}).get(time_minute, [])
        ups = set()
        for minute_list in upstream.get(endpoint, {}).values():
            ups.update(minute_list)
        return sorted(u for u in ups if u != "None")

    def get_call_chain_for_endpoint(self, endpoint):
        return {
            "upstream": self.get_endpoint_upstream(endpoint),
            "downstream": self.get_endpoint_downstream(endpoint),
        }
