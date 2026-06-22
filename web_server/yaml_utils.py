# -*- coding: utf-8 -*-
"""YAML 清洗 / 断言标准化工具"""
import re


def trim_yaml_head(yaml_text):
    """跳过 YAML 正文前的裸文本行（AI 常在第一行输出标题/摘要）"""
    lines = yaml_text.split("\n")
    start = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.match(r'^[a-zA-Z_][\w]*:\s*$', s):
            start = i
            break
        if re.match(r'^\s+[\w.-]+\s*:', line):
            start = i
            break
        if s.startswith(("-", "---", "...")):
            start = i
            break
    return "\n".join(lines[start:])


def sanitize_yaml_scalars(yaml_text):
    """自动给含特殊字符的裸值加引号"""
    yaml_text = trim_yaml_head(yaml_text)
    lines = yaml_text.split("\n")
    out = []
    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        line = re.sub(r"(\s+value:\s+)'(\d+)'", r"\1\2", line)
        if re.search(r":''\s*$", line):
            line = re.sub(r":''\s*$", ":", line)
        m = re.match(r"^(\s*)([^:]+):\s+(\S.*)$", line)
        if not m:
            out.append(line)
            continue
        indent, key, val = m.group(1), m.group(2), m.group(3)
        v = val.strip()
        if not v or v.startswith(("'", '"', "{", "[")):
            out.append(line)
            continue
        if v.startswith(("|", ">")):
            rest = v[1:]
            if rest in ('', '-', '+', '>-', '>+', '|-', '|+'):
                out.append(line)
                continue
        if v.startswith("!"):
            if v != '!=' and not v.startswith('!!'):
                out.append(line)
                continue
        if v and v[0] in ('>', '|', '!'):
            q = '"' if "'" in v else "'"
            out.append("%s%s: %s%s%s" % (indent, key, q, v, q))
            continue
        dangerous = any(ch in v for ch in ("*", "&", "!", "{", "}", "[", "]", "#", "%", "@", "`", ","))
        has_colon_or_hash = (":" in v or "#" in v) and not v.startswith("http")
        if dangerous or (has_colon_or_hash and not (v.startswith("$") or v.startswith("http"))):
            q = '"' if "'" in v else "'"
            out.append("%s%s: %s%s%s" % (indent, key, q, v, q))
        else:
            out.append(line)
    return "\n".join(out)


def normalize_yaml_assertions(yaml_text):
    """标准化断言：加 status_code: 200 + 只保留 code 断言字段"""
    lines = yaml_text.split('\n')
    result = []
    in_assert = False
    has_status_code = False
    has_code = False
    assert_indent = 0

    for raw in lines:
        stripped = raw.rstrip()
        indent = len(raw) - len(raw.lstrip())
        is_blank = not stripped or stripped.startswith('#')
        if is_blank:
            result.append(raw)
            continue
        if indent <= 2 and stripped.endswith(':'):
            key = stripped.split(':')[0].strip()
            if key and not key.startswith('#') and key != 'case_common' and ' ' not in key:
                if in_assert and not has_status_code:
                    result.append(' ' * (assert_indent + 2) + 'status_code: 200')
                in_assert = False
                has_status_code = False
                has_code = False
        if stripped.lstrip() == 'assert:':
            if in_assert and not has_status_code:
                result.append(' ' * (assert_indent + 2) + 'status_code: 200')
            in_assert = True
            assert_indent = indent
            has_status_code = False
            has_code = False
            result.append(raw)
            continue
        if not in_assert:
            result.append(raw)
            continue
        child_indent = assert_indent + 2
        if indent == child_indent:
            m = re.match(r'^(\s*)([^:]+):', raw)
            if m:
                child_key = m.group(2).strip()
                if child_key == 'status_code':
                    has_status_code = True
                    has_code = False
                    result.append(raw)
                    continue
                if child_key == 'code':
                    has_code = True
                    result.append(raw)
                    continue
                has_code = False
                continue
        if indent > child_indent:
            if has_code:
                result.append(raw)
            continue
        continue

    if in_assert and not has_status_code:
        result.append(' ' * (assert_indent + 2) + 'status_code: 200')
    return '\n'.join(result)
