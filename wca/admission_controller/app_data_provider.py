# Copyright (c) 2020 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License

from dataclasses import dataclass
from wca.prometheus import Prometheus


@dataclass
class Queries:
    APP_WSS: str = 'app_req{dim="wss"}'
    APP_RSS: str = 'app_req{dim="mem"}'


class AppDataProvider:

    def __init__(self, prometheus: Prometheus, queries: Queries = Queries()):
        self.prometheus = prometheus
        self.queries = queries

    def get_wss(self):
        return self._get_requested_app_metric(Queries.APP_WSS)

    def get_rss(self):
        return self._get_requested_app_metric(Queries.APP_RSS)

    def _get_requested_app_metric(self, query):
        """Group by >>app<< label"""
        query_result = self.prometheus.do_query(query)
        app_metrics = {}
        for row in query_result:
            app_metrics[row['metric']['app']] = float(row['value'][1])
        return app_metrics
