"""知识库检索的 ACL 预过滤。

对应 Java `DefaultKnowledgeBaseVectorService.accessFilter` 与
`knowledge.AccessScope` / `knowledge.DocumentVisibility`。

ACL 必须在 provider 侧**预过滤**而不是检索后裁剪：后裁剪会让 topK 被
无权文档占满，既漏召回又泄露存在性。三段必选断言（tenantId /
knowledgeBaseId / status=ACTIVE）之后，非 tenantAdmin 主体再追加
visibility 决策树，以 OR 拼接，任一分支命中即可见。

空部门/账号集合时对应分支自然不命中 —— 这是有意的安全降级：
没有部门归属的主体只能看到 COMPANY 文档。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .filters import VectorFilter, and_, contains_any, eq, or_


class DocumentVisibility(StrEnum):
    COMPANY = "COMPANY"
    DEPARTMENT = "DEPARTMENT"
    CUSTOM = "CUSTOM"
    PRIVATE = "PRIVATE"


@dataclass(frozen=True, slots=True)
class AccessScope:
    tenant_id: int
    department_ids: frozenset[str] = field(default_factory=frozenset)
    principal_ids: frozenset[str] = field(default_factory=frozenset)
    tenant_admin: bool = False

    def __post_init__(self) -> None:
        if self.tenant_id is None:
            raise ValueError("tenant_id must not be None")
        object.__setattr__(self, "department_ids", frozenset(self.department_ids or ()))
        object.__setattr__(self, "principal_ids", frozenset(self.principal_ids or ()))


def build_access_filter(knowledge_base_id: str, scope: AccessScope) -> VectorFilter:
    """构造可下推的 ACL 复合过滤。"""
    if not isinstance(scope, AccessScope):
        raise TypeError("scope must be an AccessScope")
    mandatory: list[VectorFilter] = [
        eq("tenantId", scope.tenant_id),
        eq("knowledgeBaseId", knowledge_base_id),
        eq("status", "ACTIVE"),
    ]
    if not scope.tenant_admin:
        visibility: list[VectorFilter] = [
            eq("visibility", DocumentVisibility.COMPANY.value)
        ]
        if scope.department_ids:
            # frozenset 迭代序不稳定，排序保证同一 scope 编译出同一条 DSL。
            departments = sorted(scope.department_ids)
            visibility.append(
                and_(
                    eq("visibility", DocumentVisibility.DEPARTMENT.value),
                    contains_any("allowedDepartmentIds", departments),
                )
            )
            visibility.append(
                and_(
                    eq("visibility", DocumentVisibility.CUSTOM.value),
                    contains_any("allowedDepartmentIds", departments),
                )
            )
        if scope.principal_ids:
            principals = sorted(scope.principal_ids)
            visibility.append(
                and_(
                    eq("visibility", DocumentVisibility.CUSTOM.value),
                    contains_any("allowedPrincipalIds", principals),
                )
            )
            visibility.append(
                and_(
                    eq("visibility", DocumentVisibility.PRIVATE.value),
                    contains_any("allowedPrincipalIds", principals),
                )
            )
        mandatory.append(or_(*visibility))
    return and_(*mandatory)


__all__ = ["DocumentVisibility", "AccessScope", "build_access_filter"]