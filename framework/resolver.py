"""变量解析器 —— 处理 YAML 中的 ${{...}} 模板语法和 $cache{...} 缓存引用。"""

from __future__ import annotations
import re
import random
import string
import time
import uuid
from typing import Any, Callable, Dict, Optional, Union
from .config import Config
from .context import get_global_context

# ── 内置函数注册表 ──

class BuiltinFunctions:
    """${{host()}} / ${{random_int()}} 等内置函数"""

    @staticmethod
    def host() -> str:
        config = Config()
        return config.host

    @staticmethod
    def random_int(min_val: int = 100000, max_val: int = 999999) -> int:
        return random.randint(min_val, max_val)

    @staticmethod
    def random_str(length: int = 8) -> str:
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    @staticmethod
    def timestamp() -> int:
        return int(time.time())

    @staticmethod
    def timestamp_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def uuid4() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def date(fmt: str = "%Y-%m-%d") -> str:
        return time.strftime(fmt, time.localtime())

    @staticmethod
    def datetime(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        return time.strftime(fmt, time.localtime())

    @staticmethod
    def phone() -> str:
        """随机手机号"""
        prefixes = ["130", "131", "132", "133", "134", "135", "136",
                     "137", "138", "139", "150", "151", "152", "153",
                     "155", "156", "157", "158", "159", "166", "170",
                     "176", "177", "178", "180", "181", "182", "183",
                     "184", "185", "186", "187", "188", "189"]
        return random.choice(prefixes) + ''.join(random.choices(string.digits, k=8))

    @staticmethod
    def get(var_name: str, default: Any = None) -> Any:
        """从运行时上下文获取变量: ${{get(token)}}"""
        return get_global_context().get(var_name, default)


class VariableResolver:
    """变量解析器

    支持的语法:
    - ${{host()}}                    → 配置中的 host
    - ${{random_int()}}              → 随机整数
    - ${{random_int(1000,9999)}}  → 带参数的随机整数
    - ${{random_str(10)}}           → 随机字符串
    - ${{timestamp()}}               → Unix 时间戳
    - ${{uuid4()}}                   → UUID4
    - ${{phone()}}                   → 随机手机号
    - ${{get(token)}}               → 运行时变量
    - $cache{key}                    → 缓存值
    - int:${{random_int()}}         → 带类型标注的值（去掉引号）
    """

    _BUILTIN_PATTERN = re.compile(r'\${{(.*?)}}')
    _CACHE_PATTERN = re.compile(r'\$cache{(.*?)}')
    _TYPED_PATTERN = re.compile(r"(?:int|bool|float|list|dict|tuple):\s*['\"]?\${{(.*?)}}['\"]?")

    def __init__(self, extra_functions: Optional[Dict[str, Callable]] = None):
        self._funcs = {
            name: getattr(BuiltinFunctions, name)
            for name in dir(BuiltinFunctions)
            if not name.startswith("_") and callable(getattr(BuiltinFunctions, name))
        }
        if extra_functions:
            self._funcs.update(extra_functions)

    def register(self, name: str, func: Callable):
        """注册自定义函数"""
        self._funcs[name] = func

    def resolve(self, value: Any) -> Any:
        """递归解析任意类型的值，替换所有 ${{...}} 和 $cache{...}"""
        if isinstance(value, str):
            return self._resolve_string(value)
        elif isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(v) for v in value]
        else:
            return value

    def _resolve_string(self, s: str) -> Any:
        """解析字符串中的模板变量"""
        # 1) 处理带类型标注的 ${{...}}
        typed_match = self._TYPED_PATTERN.fullmatch(s)
        if typed_match:
            return self._call_function(typed_match.group(1))

        # 2) 处理 ${{...}}
        def replace_builtin(m: re.Match) -> str:
            result = self._call_function(m.group(1))
            return str(result)

        s = self._BUILTIN_PATTERN.sub(replace_builtin, s)

        # 3) 处理 $cache{...}
        def replace_cache(m: re.Match) -> str:
            key = m.group(1)
            val = get_global_context().get(key)
            return str(val) if val is not None else m.group(0)

        s = self._CACHE_PATTERN.sub(replace_cache, s)

        return s

    def _call_function(self, expr: str) -> Any:
        """解析并调用表达式，如 host() / random_int(1000,9999)"""
        expr = expr.strip()

        # 支持字面量：${{True}}, ${{123}}, ${{"hello"}}
        if expr.lower() == "true":
            return True
        if expr.lower() == "false":
            return False
        if expr.lower() == "null" or expr.lower() == "none":
            return None
        if expr.isdigit():
            return int(expr)
        if (expr.startswith('"') and expr.endswith('"')) or \
           (expr.startswith("'") and expr.endswith("'")):
            return expr[1:-1]

        # 函数调用: func_name(args)
        match = re.match(r'^(\w+)\s*\(\s*(.*?)\s*\)$', expr)
        if match:
            func_name = match.group(1)
            args_str = match.group(2)

            if func_name not in self._funcs:
                raise ValueError(f"未注册的函数: {func_name}，已注册: {list(self._funcs.keys())}")

            args = self._parse_args(args_str)
            return self._funcs[func_name](*args)

        # 兜底：若整个字符串只包含一个 ${{var}} 且无括号，当作变量名查询
        val = get_global_context().get(expr)
        if val is not None:
            return val

        raise ValueError(f"无法解析表达式: ${{{expr}}}")

    @staticmethod
    def _parse_args(args_str: str) -> list:
        """简单参数解析，支持字符串、整数、浮点数、布尔值"""
        if not args_str.strip():
            return []

        args = []
        for part in args_str.split(","):
            part = part.strip()
            if not part:
                continue
            # 字符串
            if (part.startswith('"') and part.endswith('"')) or \
               (part.startswith("'") and part.endswith("'")):
                args.append(part[1:-1])
            # 布尔
            elif part.lower() == "true":
                args.append(True)
            elif part.lower() == "false":
                args.append(False)
            elif part.lower() in ("null", "none"):
                args.append(None)
            # 浮点
            elif "." in part and part.replace(".", "").lstrip("-").isdigit():
                args.append(float(part))
            # 整数
            elif part.lstrip("-").isdigit():
                args.append(int(part))
            else:
                args.append(part)
        return args
