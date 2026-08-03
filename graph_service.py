# -*- coding: utf-8 -*-

"""
@Project ：cutover
@File ： graph_service.py
@Author ：v_liyao13
@Date ： 2025/7/28 16:37
"""

import json
import requests
import uuid
from requests.auth import HTTPBasicAuth
from typing import Dict, List, Any, Tuple

from libs.logger import get_logger

log = get_logger(__name__)


class GraphService:
    """
    割接知识图谱服务（根据新数据结构优化）
    顶点类型：CUTOVER_TASK, CUTOVER_PHASE, OPERATION, RISK, EXPERIENCE, NOTICE
    """

    # 顶点类型定义
    VERTEX_LABELS = {
        "CUTOVER_TASK": "CUTOVER_TASK",
        "CUTOVER_PHASE": "CUTOVER_PHASE",
        "OPERATION": "OPERATION",
        "RISK": "RISK",
        "EXPERIENCE": "EXPERIENCE",
        "NOTICE": "NOTICE"
    }

    # 边关系类型定义
    EDGE_TYPES = {
        "CONTAINS": "TASK2PHASE",  # 任务到阶段
        "HAS_OPERATION": "PHASE2OPERATION",  # 阶段到操作
        "HAS_RISK": "PHASE2RISK",  # 阶段到风险
        "RELATES_TO_EXP": "RISK2EXPERIENCE",  # 风险到经验
        "HAS_NOTICE": "PHASE2NOTICE"  # 阶段到注意
    }

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

        self.vertex_url = f"http://{self.graph_host}:{self.graph_port}/graphspaces/{self.graph_spaces}/graphs/{self.graph_graph}/graph/vertices"
        self.edge_url = f"http://{self.graph_host}:{self.graph_port}/graphspaces/{self.graph_spaces}/graphs/{self.graph_graph}/graph/edges"

    def import_cut_over_knowledge(self, knowledge_data: Dict[str, Any]):
        """
        导入割接知识图谱数据
        :param knowledge_data: 符合新结构的割接知识数据
        """
        try:
            # 创建所有顶点
            self._create_vertices_with_phase_association(knowledge_data)

            # 创建所有边关系
            self._create_edges_with_phase_association(knowledge_data)

            log.info("割接知识图谱数据导入成功!")
            return True
        except Exception as e:
            log.debug(f"导入割接知识图谱数据失败: {str(e)}")
            return False

    def _create_vertices_with_phase_association(self, knowledge_data: Dict[str, Any]):
        """创建所有顶点（基于阶段ID关联）"""

        if knowledge_data['execution_content'] == {}:
            return

        # 1. 割接环节顶点
        work_order_number = knowledge_data['work_order_number']
        phase_ids = []
        for phase in knowledge_data["execution_content"].keys():
            phase_id = '_'.join([work_order_number, phase])
            phase_ids.append(phase_id)
            self._create_vertex(
                "CUTOVER_PHASE",
                {"phase_id": phase_id, "phase_type": phase},
                vertex_id=phase_id
            )
        self._create_vertex(
            "CUTOVER_TASK",
            {
                "work_order_number": work_order_number,
                "phase_ids": json.dumps(phase_ids, ensure_ascii=False)
            },
            vertex_id=work_order_number
        )

        for phase_type, name in knowledge_data["execution_content"].items():
            # 2. 操作内容顶点（基于阶段ID生成顶点ID）
            for key, content in name.items():
                phase_id = '_'.join([work_order_number, phase_type, key])
                if key == 'operation':
                    self._create_vertex(
                        "OPERATION",
                        {
                            "phase_id": phase_id,
                            "operation_name": "",
                            "execution_content": content
                        },
                        vertex_id=phase_id
                    )
                if key == 'risk':
                    self._create_vertex(
                        "RISK",
                        {
                            "phase_id": phase_id,
                            "risk_name": content,
                            "severity": '中度'
                        },
                        vertex_id=phase_id
                    )

                if key == 'experience':
                    self._create_vertex(
                        "EXPERIENCE",
                        {
                            "phase_id": phase_id,
                            "exp_content": content,
                            "exp_name": ""
                        },
                        vertex_id=phase_id
                    )
                if key == 'notice':
                    self._create_vertex(
                        "NOTICE",
                        {
                            "phase_id": phase_id,
                            "notice_content": content,
                            "notice_name": ""
                        },
                        vertex_id=phase_id
                    )

        return

    def _create_vertex(self, vertex_type: str, properties: Dict[str, Any], vertex_id: str = None):
        """创建顶点（支持自定义ID）"""
        if not vertex_id:
            vertex_id = f"{vertex_type}_{str(uuid.uuid4())}"

        # 构建顶点JSON
        vertex_json = {
            "label": vertex_type.upper(),  # 使用大写的顶点类型作为标签
            "id": vertex_id,
            "type": "vertex",
            "properties": properties
        }

        response = requests.post(
            self.vertex_url,
            # headers=self.headers,
            json=vertex_json,
            auth=HTTPBasicAuth(self.__graph_user, self.__graph_passwd)
        )

        if response.status_code in (200, 201):
            log.info(f"顶点创建成功: {vertex_type} ({vertex_id})")
        else:
            log.debug(
                f"顶点创建失败: {vertex_type} ({vertex_id}), status={response.status_code}, msg={response.text}")

    def _create_edges_with_phase_association(self, knowledge_data: Dict[str, Any]):
        """创建所有边关系（完全基于 phase_id 关联）"""
        if knowledge_data['execution_content'] == {}:
            return

        work_order_number = knowledge_data['work_order_number']
        for phase_type, name in knowledge_data["execution_content"].items():
            source_id = work_order_number
            target_id = '_'.join([work_order_number, phase_type])
            self._create_edge(
                source_id=source_id,
                target_id=target_id,
                edge_label="TASK2PHASE",
                phase_id=source_id
            )
            for key, content in name.items():
                source_id = '_'.join([work_order_number, phase_type])
                target_id = '_'.join([work_order_number, phase_type, key])
                if key == 'operation':
                    self._create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_label="PHASE2OPERATION",
                        phase_id=source_id
                    )
                if key == 'risk':
                    self._create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_label="PHASE2RISK",
                        phase_id=source_id
                    )
                if key == 'experience':
                    source_id = '_'.join([work_order_number, phase_type, 'risk'])
                    self._create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_label="RISK2EXPRIENCE",
                        phase_id=source_id
                    )
                if key == 'notice':
                    self._create_edge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_label="PHASE2NOTICE",
                        phase_id=source_id
                    )

    def _create_edge(self, source_id: str, target_id: str, edge_label: str, phase_id: str):
        """
        创建边关系
        :param source_id: 源顶点ID
        :param target_id: 目标顶点ID
        :param edge_label: 边标签
        """
        if not source_id or not target_id:
            log.debug(f"创建边失败: 缺少源或目标顶点 ({edge_label})")
            return

        # 构建符合规范的边数据
        edge_json = {
            "label": edge_label,
            "outV": source_id,
            "inV": target_id,
            "properties": {
                "phase_id": phase_id
            }
        }

        try:
            response = requests.post(
                self.edge_url,
                json=edge_json,
                auth=HTTPBasicAuth(self.__graph_user, self.__graph_passwd),
                timeout=10
            )

            if response.status_code in (200, 201):
                log.info(f"边创建成功: {source_id} -[{edge_label}]-> {target_id}")
            else:
                log.debug(f"边创建失败 ({response.status_code}): {response.text}")
        except Exception as e:
            log.debug(f"边创建请求异常: {str(e)}")
