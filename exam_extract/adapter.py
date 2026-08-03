# -*- coding: utf-8 -*-
"""Stage 3: import :class:`IntermediateJson` into HugeGraph via its REST API.

Vertices that already exist are skipped (counted as duplicated); edges of
label ``belongs_to_type`` resolve their ``inV`` through a preloaded
question_type name -> id cache.
"""
from typing import Any, Dict, Tuple

import requests

from exam_extract.logger import get_logger
from exam_extract.models import Edge, IntermediateJson, Vertex

log = get_logger(__name__)


class HugeGraphAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        passwd: str,
        graphspace: str = "DEFAULT",
        graph: str = "edu",
    ):
        self.base_url = f"http://{host}:{port}/graphspaces/{graphspace}/graphs/{graph}"
        self.auth = (user, passwd)
        self._question_type_cache: Dict[str, str] = {}

    def import_data(self, data: IntermediateJson) -> Dict[str, Any]:
        self._preload_question_types()

        report: Dict[str, Any] = {
            "vertices_total": len(data.vertices),
            "vertices_created": 0,
            "vertices_duplicated": 0,
            "edges_total": len(data.edges),
            "edges_created": 0,
            "edges_failed": 0,
        }

        for v in data.vertices:
            created, duplicated = self._create_vertex(v)
            if created:
                report["vertices_created"] += 1
            if duplicated:
                report["vertices_duplicated"] += 1

        for e in data.edges:
            if self._create_edge(e):
                report["edges_created"] += 1
            else:
                report["edges_failed"] += 1

        log.info("导入完成: %s", report)
        return report

    def _preload_question_types(self) -> None:
        url = f"{self.base_url}/graph/vertices?label=question_type"
        resp = requests.get(url, auth=self.auth)
        resp.raise_for_status()
        for v in resp.json().get("vertices", []):
            name = v.get("properties", {}).get("name")
            if name:
                self._question_type_cache[name] = v.get("id")

    def _post_vertex(self, payload: Dict[str, Any]) -> requests.Response:
        url = f"{self.base_url}/graph/vertices"
        return requests.post(url, json=payload, auth=self.auth)

    def _create_vertex(self, vertex: Vertex) -> Tuple[bool, bool]:
        payload = {
            "label": vertex.label,
            "id": vertex.id,
            "type": "vertex",
            "properties": vertex.properties,
        }
        resp = self._post_vertex(payload)
        if resp.status_code in (200, 201):
            log.info("顶点创建成功: %s (%s)", vertex.label, vertex.id)
            return True, False
        if resp.status_code == 400 and "already exists" in resp.text.lower():
            log.debug("顶点已存在，跳过: %s (%s)", vertex.label, vertex.id)
            return False, True
        log.error("顶点创建失败: %s (%s): %s", vertex.label, vertex.id, resp.text)
        return False, False

    def _create_edge(self, edge: Edge) -> bool:
        url = f"{self.base_url}/graph/edges"

        inV = edge.inV
        if edge.label == "belongs_to_type":
            inV = self._question_type_cache.get(edge.inV)
            if not inV:
                log.error("题型顶点不存在: %s", edge.inV)
                return False

        payload = {
            "label": edge.label,
            "outV": edge.outV,
            "inV": inV,
            "properties": edge.properties,
        }
        resp = requests.post(url, json=payload, auth=self.auth)
        if resp.status_code in (200, 201):
            log.info("边创建成功: %s -[%s]-> %s", edge.outV, edge.label, inV)
            return True
        log.error("边创建失败: %s -[%s]-> %s: %s", edge.outV, edge.label, inV, resp.text)
        return False
