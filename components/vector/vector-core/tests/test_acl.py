"""知识库 ACL 预过滤构造。"""

from __future__ import annotations

import pytest

from atlas_richie.vector_core import (
    AccessScope,
    And,
    DocumentVisibility,
    Or,
    SpringAiVectorFilterCompiler,
    build_access_filter,
    contains_any,
    eq,
)


def _visibility_branches(tree: And) -> Or:
    return tree.filters[-1]


class TestMandatoryClauses:
    def test_always_scopes_tenant_kb_and_active(self) -> None:
        tree = build_access_filter("kb-1", AccessScope(tenant_id=7, tenant_admin=True))
        assert tree.filters[0] == eq("tenantId", 7)
        assert tree.filters[1] == eq("knowledgeBaseId", "kb-1")
        assert tree.filters[2] == eq("status", "ACTIVE")

    def test_tenant_admin_skips_visibility(self) -> None:
        tree = build_access_filter(
            "kb-1",
            AccessScope(tenant_id=7, department_ids=frozenset({"d1"}), tenant_admin=True),
        )
        assert len(tree.filters) == 3
        assert not isinstance(tree.filters[-1], Or)

    def test_non_admin_always_appends_visibility(self) -> None:
        tree = build_access_filter("kb-1", AccessScope(tenant_id=7))
        assert len(tree.filters) == 4
        assert isinstance(_visibility_branches(tree), Or)


class TestVisibilityDecisionTree:
    def test_empty_scope_sees_only_company(self) -> None:
        """无部门无账号的主体只能看 COMPANY —— 有意的安全降级。"""
        branches = _visibility_branches(
            build_access_filter("kb", AccessScope(tenant_id=1))
        ).filters
        assert branches == (eq("visibility", "COMPANY"),)

    def test_departments_add_department_and_custom_branches(self) -> None:
        branches = _visibility_branches(
            build_access_filter("kb", AccessScope(tenant_id=1, department_ids=frozenset({"d1"})))
        ).filters
        assert len(branches) == 3
        assert branches[1] == And(
            (eq("visibility", "DEPARTMENT"), contains_any("allowedDepartmentIds", ("d1",)))
        )
        assert branches[2] == And(
            (eq("visibility", "CUSTOM"), contains_any("allowedDepartmentIds", ("d1",)))
        )

    def test_principals_add_custom_and_private_branches(self) -> None:
        branches = _visibility_branches(
            build_access_filter("kb", AccessScope(tenant_id=1, principal_ids=frozenset({"u1"})))
        ).filters
        assert len(branches) == 3
        assert branches[1] == And(
            (eq("visibility", "CUSTOM"), contains_any("allowedPrincipalIds", ("u1",)))
        )
        assert branches[2] == And(
            (eq("visibility", "PRIVATE"), contains_any("allowedPrincipalIds", ("u1",)))
        )

    def test_full_scope_has_five_branches(self) -> None:
        scope = AccessScope(
            tenant_id=1, department_ids=frozenset({"d1"}), principal_ids=frozenset({"u1"})
        )
        branches = _visibility_branches(build_access_filter("kb", scope)).filters
        assert len(branches) == 5
        assert [b.filters[0].value for b in branches[1:]] == [
            "DEPARTMENT", "CUSTOM", "CUSTOM", "PRIVATE",
        ]

    def test_private_never_matches_on_department_alone(self) -> None:
        scope = AccessScope(tenant_id=1, department_ids=frozenset({"d1"}))
        compiled = SpringAiVectorFilterCompiler().compile(build_access_filter("kb", scope))
        assert "PRIVATE" not in compiled

    def test_department_ids_use_contains_any_not_in(self) -> None:
        """集合字段必须用交集语义；用 IN 会把"记录部门 ∈ 用户部门"错当成标量归属。"""
        scope = AccessScope(tenant_id=1, department_ids=frozenset({"d1"}))
        tree = build_access_filter("kb", scope)
        department_branch = _visibility_branches(tree).filters[1]
        assert department_branch.filters[1].field == "allowedDepartmentIds"
        assert type(department_branch.filters[1]).__name__ == "ContainsAny"


class TestScope:
    def test_tenant_id_required(self) -> None:
        with pytest.raises(ValueError):
            AccessScope(tenant_id=None)

    def test_none_collections_normalize_to_empty(self) -> None:
        scope = AccessScope(tenant_id=1, department_ids=None, principal_ids=None)
        assert scope.department_ids == frozenset()
        assert scope.principal_ids == frozenset()

    def test_collections_are_snapshots(self) -> None:
        departments = {"d1"}
        scope = AccessScope(tenant_id=1, department_ids=departments)
        departments.add("d2")
        assert scope.department_ids == frozenset({"d1"})

    def test_deterministic_compilation(self) -> None:
        compiler = SpringAiVectorFilterCompiler()
        scope = AccessScope(
            tenant_id=1, department_ids=frozenset({"d3", "d1", "d2"}),
            principal_ids=frozenset({"u2", "u1"}),
        )
        first = compiler.compile(build_access_filter("kb", scope))
        for _ in range(5):
            assert compiler.compile(build_access_filter("kb", scope)) == first
        assert "['d1', 'd2', 'd3']" in first
        assert "['u1', 'u2']" in first

    def test_visibility_vocabulary(self) -> None:
        assert [v.value for v in DocumentVisibility] == [
            "COMPANY", "DEPARTMENT", "CUSTOM", "PRIVATE",
        ]