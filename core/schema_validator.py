"""schema_validator.py --- 按 schema 校验 front matter。

对一份 meta 执行 required/enum/type/cross_ref 检查，返回结构化校验结果。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import schemas


@dataclass
class ValidationIssue:
    """单条校验问题。"""
    field: str
    severity: str          # "error" | "warning" | "info"
    message: str


@dataclass
class ValidationResult:
    """校验结果。"""
    valid: bool                            # errors 为空则为 True
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    info: list[ValidationIssue] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)

    @property
    def all_issues(self) -> list[ValidationIssue]:
        return self.errors + self.warnings + self.info


def validate(meta: dict[str, Any], kind: str, store=None) -> ValidationResult:
    """校验一份 meta 是否符合其类型 schema。

    Args:
        meta:  front matter 字典
        kind:  文档类型（characters/npcs/scenes/locations/items/story-arcs/state-records/terminology）
        store: Store 实例（可选，提供时执行 cross_ref 检查）

    Returns:
        ValidationResult
    """
    schema = schemas.SCHEMAS.get(kind)
    if not schema:
        return ValidationResult(valid=True, summary={"info": "no schema for kind", "kind": kind})

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    info: list[ValidationIssue] = []

    # ---- 系统字段提示 ----
    for sys_field in schemas.SYSTEM_FIELDS:
        if sys_field in meta:
            info.append(ValidationIssue(
                sys_field, "info",
                f"系统字段 {sys_field} 不应出现在 front matter 中（由文件名/系统自动管理），"
                f"读取时会被忽略"
            ))

    # ---- 1. 必填字段检查 ----
    required_ok = 0
    required_missing = 0
    for field in schema.get("required", []):
        val = meta.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(ValidationIssue(
                field, "error",
                f"缺少必填字段 {field}"
            ))
            required_missing += 1
        else:
            required_ok += 1

    # ---- 2. 字段规范检查 ----
    enum_ok = 0
    enum_invalid = 0
    type_ok = 0
    type_mismatch = 0

    for field, spec in schema.get("fields", {}).items():
        val = meta.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue  # 空值不报错（由 required 检查处理）

        # 枚举检查
        if spec["type"] == "enum":
            if val not in spec["values"]:
                warnings.append(ValidationIssue(
                    field, "warning",
                    f"字段 {field} 的值 '{val}' 不在枚举范围内：{spec['values']}"
                ))
                enum_invalid += 1
            else:
                enum_ok += 1

        # 类型检查
        elif spec["type"] == "int":
            if isinstance(val, int):
                type_ok += 1
                if "range" in spec:
                    lo, hi = spec["range"]
                    if not (lo <= val <= hi):
                        warnings.append(ValidationIssue(
                            field, "warning",
                            f"字段 {field} 值 {val} 超出范围 [{lo}, {hi}]"
                        ))
            else:
                warnings.append(ValidationIssue(
                    field, "warning",
                    f"字段 {field} 应为整数，当前为 {type(val).__name__}"
                ))
                type_mismatch += 1

        elif spec["type"] == "list":
            if isinstance(val, list):
                type_ok += 1
                # 检查列表元素类型
                item_type = spec.get("item_type")
                if item_type == "str":
                    non_str = [i for i in val if not isinstance(i, str)]
                    if non_str:
                        warnings.append(ValidationIssue(
                            field, "warning",
                            f"字段 {field} 的列表元素应均为字符串，发现 {len(non_str)} 个非字符串元素"
                        ))
            else:
                warnings.append(ValidationIssue(
                    field, "warning",
                    f"字段 {field} 应为列表，当前为 {type(val).__name__}"
                ))
                type_mismatch += 1

        elif spec["type"] == "str":
            if isinstance(val, str):
                type_ok += 1
            else:
                warnings.append(ValidationIssue(
                    field, "warning",
                    f"字段 {field} 应为字符串，当前为 {type(val).__name__}"
                ))
                type_mismatch += 1

    # ---- 3. 跨文件引用检查 ----
    if store and "cross_refs" in schema:
        for field, ref_kind in schema["cross_refs"].items():
            val = meta.get(field)
            if val and isinstance(val, str) and val.strip():
                if store.read(ref_kind, val) is None:
                    warnings.append(ValidationIssue(
                        field, "warning",
                        f"字段 {field} 引用的 {ref_kind}/{val} 不存在"
                    ))

    # ---- 4. 未知字段检查 ----
    known_fields = set(schema.get("fields", {}).keys()) | schemas.SYSTEM_FIELDS
    for key in meta:
        if key not in known_fields and not key.startswith("_"):
            warnings.append(ValidationIssue(
                key, "warning",
                f"未知字段 {key}（不在 {kind} schema 中）"
            ))

    valid = len(errors) == 0
    summary = {
        "required_ok": required_ok,
        "required_missing": required_missing,
        "enum_ok": enum_ok,
        "enum_invalid": enum_invalid,
        "type_ok": type_ok,
        "type_mismatch": type_mismatch,
    }

    return ValidationResult(
        valid=valid,
        errors=errors,
        warnings=warnings,
        info=info,
        summary=summary,
    )
