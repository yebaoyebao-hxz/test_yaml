"""命令行入口 —— 独立运行 YAML 测试，不依赖 pytest。"""

from __future__ import annotations
import sys
import argparse
import json
from pathlib import Path

from .runner import TestRunner


def main():
    parser = argparse.ArgumentParser(
        prog="rabbit-test",
        description="兔子测试框架 CLI —— 基于 YAML 的 API 自动化测试",
    )
    parser.add_argument(
        "yaml_file",
        help="YAML 用例文件路径，如 data/兔子.yaml",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="框架配置文件路径，如 common/config.yaml",
    )
    parser.add_argument(
        "-f", "--filter",
        default=None,
        help="用例过滤（按 case_id 或 detail 模糊匹配）",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="结果输出 JSON 文件路径",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="不打印报告",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出",
    )

    args = parser.parse_args()

    if not Path(args.yaml_file).exists():
        print(f"错误: 文件不存在 - {args.yaml_file}", file=sys.stderr)
        sys.exit(1)

    with TestRunner(args.yaml_file, config_path=args.config) as runner:
        results = runner.run(case_filter=args.filter)

        if not args.no_report:
            runner.print_report()

        # JSON 输出
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            data = runner.to_dict()
            output_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"\n结果已写入: {args.output}")

        # 退出码
        if not runner.passed:
            sys.exit(1)


if __name__ == "__main__":
    main()
