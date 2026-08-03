# -*- coding: UTF-8 -*-

"""
Description:
Authors: zhangyayu(v_zhangyayu02@baidu.com)
Date:    2025/4/1
"""
import json
from typing import Dict, List, Any, Tuple

import requests
from requests.auth import HTTPBasicAuth

from libs.logger import get_logger

log = get_logger(__name__)


class GraphSearch:

    def __init__(self, graph_spaces, graph_graph, graph_host, graph_port, graph_user, graph_passwd):
        """
        初始化图谱服务
        :param config: 图数据库配置
        """
        self.graph_spaces = graph_spaces
        self.graph_graph = graph_graph
        self.graph_host = graph_host
        self.graph_port = graph_port
        self.__graph_user = graph_user
        self.__graph_passwd = graph_passwd
        self.gremlin_url = f"http://{self.graph_host}:{self.graph_port}/gremlin"

    def node_search(self, work_order_number: str, phase_type: str):
        try:
            result_content = '暂无相关经验参考'
            gremlin_content = "g.V().has('phase_id', '{}').out()".format(work_order_number + "_" + phase_type)
            log.info(gremlin_content)
            graph_data = self.request_by_graph(gremlin_content)

            log.info(graph_data)

            if not graph_data:
                log.info(result_content)
                return result_content
            result_content = []
            for item in graph_data:
                if item['label'] == 'OPERATION':
                    operation = item['properties'].get('execution_content', '').split('</think>')[-1]
                    if operation:
                        operation = '阶段操作内容: {}'.format(operation)
                        result_content.append(operation)
                    continue
                elif item['label'] == 'EXPERIENCE':
                    experience = item['properties'].get('exp_content', '').split('</think>')[-1]
                    if experience:
                        experience = '相关经验参考: {}'.format(experience)
                        result_content.append(experience)
                    continue
                elif item['label'] == 'RISK':
                    risk = item['properties'].get('risk_name', '').split('</think>')[-1]
                    if risk:
                        risk = '阶段蕴含风险: {}'.format(risk)
                        result_content.append(risk)
                    continue
                elif item['label'] == 'NOTICE':
                    notice = item['properties'].get('notice_content', '').split('</think>')[-1]
                    if notice:
                        notice = '主要注意事项: {}'.format(notice)
                        result_content.append(notice)
                    continue
            if len(result_content) == 0:
                result_content = '暂无相关经验参考'
                return result_content

            result_content = '工单号:{}\n\n阶段类型:{}\n\n'.format(work_order_number, phase_type) + '\n\n'.join(
                result_content)
            log.info(result_content)
            return result_content
        except Exception as e:
            log.debug('搜索失败 : {}'.format(e))
        return '搜索失败'

    def request_by_graph(self, gremlin_content):
        graph_data = []
        try:
            gremlin_json = {
                "gremlin": gremlin_content,
                "language": "gremlin-groovy",
                "aliases": {
                    "graph": "{}-{}".format(self.graph_spaces, self.graph_graph),
                    "g": "__g_{}-{}".format(self.graph_spaces, self.graph_graph)
                }
            }
            response = requests.post(
                self.gremlin_url,
                json=gremlin_json,
                auth=HTTPBasicAuth(self.__graph_user, self.__graph_passwd)
            )
            if response.status_code == 200:
                graph_data = json.loads(json.dumps(response.json(), ensure_ascii=False))['result']['data']
        except Exception as e:
            log.debug('gremlin 请求失败 : {}'.format(e))
        return graph_data
