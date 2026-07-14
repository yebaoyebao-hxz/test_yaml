import random
import re
import sys
import time
import yaml
import threading

sys.path.insert(0, 'E:\\yebao\\test_yaml')
from framework.http_client import HttpClient
from framework.config import Config
from framework.models import AssertOperator

# ============================================================
# 1. 变量替换（JMeter风格 ${__Random(1,999)}）
# ============================================================
_RANDOM_RE = re.compile(r'\$\{__Random\((\d+),(\d+)\)\}')

def resolve_dynamic_data(data_dict: dict):
    """解析 data 中的动态变量，如 roomId: '${__Random(1,999)}'"""
    resolved = {}
    for k, v in data_dict.items():
        m = _RANDOM_RE.match(str(v))
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            resolved[k] = random.randint(lo, hi)
        else:
            resolved[k] = v
    return resolved

# ============================================================
# 2. 单次 HTTP 请求（复用 HttpClient.session）
# ============================================================

def send_one(client, task):
    """发送一次 HTTP 请求，返回 (成功?, 耗时ms, 状态码)"""
    host = task['host']
    if not host.startswith('http://') and not host.startswith('https://'):
        full_url = 'https://' + host.rstrip('/') + task['url'].lstrip('/')
    else:
        full_url = host.rstrip('/') + '/' + task['url'].lstrip('/')

    body = resolve_dynamic_data(task.get('body', {}))
    headers = dict(task.get('headers', {}))
    timeout_s = task.get('timeout', 5000) / 1000.0
    if timeout_s <= 0:
        timeout_s = 5.0

    t0=time.time()
    try:
        method = task.get('method', 'POST').upper()
        resp = client.session.request(method, full_url, json=body, headers=headers, timeout=timeout_s)
        lat = round((time.time() - t0) * 1000, 1)
        return (resp.status_code == 200, lat, resp.status_code)
    except Exception:
        lat = round((time.time() - t0) * 1000, 1)
        return (False, lat, 0)

# ============================================================
# 3. YAML 解析（轻量，不污染 CaseParser）
# ============================================================

def parse_stress_yaml(path):
    """读取 YAML 文件，返回可执行的压测任务列表"""
    with open(path, 'r', encoding='utf-8') as f:
        raw = yaml.safe_load(f)

    tasks = []
    for key, value in raw.items():
        # 跳过元信息
        if key.startswith('case_common'):
            continue

        if not isinstance(value, dict):
            continue

        if value.get('is_run') is False:
            continue

        concurrency = int(value.get('concurrency', 0))
        duration = int(value.get('duration', 0))
        if concurrency <= 0 or duration <= 0:
            print(f'  ⚠ 跳过 {key}: 并发或时长为0')
            continue

        tasks.append({
            # HTTP 请求
            'name': key,
            'host': value.get('host', ''),
            'url': value.get('url', ''),
            'method': value.get('method', 'POST'),
            'headers': value.get('headers') or {},
            'data': value.get('data') or {},
            # 压测参数
            'stress_type': value.get('stress_type', ''),
            'detail': value.get('detail', ''),
            'concurrency': concurrency,
            'duration': duration,
            'ramp_up': int(value.get('ramp_up', 0)),
            'timeout': int(value.get('timeout', 5000)),
            # 断言
            'assert': value.get('assert') or {},
        })

    return tasks


# ============================================================
# 4. 并发执行引擎（线程池 + 爬坡）
# ============================================================

def run_stress(task, client):
    """按 task 参数启动多线程并发压测，返回所有请求结果列表"""
    results = []
    lock = threading.Lock()
    stop_flag = threading.Event()
    duration = task['duration']
    concurrency = task['concurrency']
    ramp_up = task['ramp_up']

    def worker():
        deadline = time.time() + duration
        while time.time() < deadline:
            if stop_flag.is_set():
                return
            ok, lat, code = send_one(client, task)
            with lock:
                results.append((ok, lat, code))

    threads = []
    interval = ramp_up / concurrency if concurrency > 0 else 0

    print(f'  启动 {concurrency} 并发  爬坡 {ramp_up}s  持续 {duration}s')

    for i in range(concurrency):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)
        if interval > 0:
            time.sleep(interval)

    for t in threads:
        t.join()

    return results

# ============================================================
# 5. 指标计算
# ============================================================

def calc_metrics(results, duration_sec):
    """从原始请求结果计算性能指标"""
    total = len(results)
    if total == 0:
        return dict.fromkeys(
            ['total', 'success', 'failed', 'error_rate', 'tps',
             'avg_rt', 'min_rt', 'max_rt', 'p50', 'p90', 'p95', 'p99'], 0)

    ok_count = sum(1 for r in results if r[0])
    latencies = sorted([r[1] for r in results])
    n = len(latencies)

    def pct(p):
        return latencies[min(int(n * p), n - 1)]

    return {
        'total':      total,
        'success':    ok_count,
        'failed':     total - ok_count,
        'error_rate': round((total - ok_count) / total, 4),
        'tps':        round(total / duration_sec, 1),
        'avg_rt':     round(sum(latencies) / n, 1),
        'min_rt':     latencies[0],
        'max_rt':     latencies[-1],
        'p50':        pct(0.50),
        'p90':        pct(0.90),
        'p95':        pct(0.95),
        'p99':        pct(0.99),
        'success_rate': round((ok_count / total) , 4),
    }

# ============================================================
# 6. 压测断言校验（复用 AssertOperator 枚举）
# ============================================================

# YAML 操作符 → 枚举映射
_OP_MAP = {
    '==': AssertOperator.EQ,
    '!=': AssertOperator.NOT_EQ,
    '>':  AssertOperator.GT,
    '>=': AssertOperator.GE,
    '<':  AssertOperator.LT,
    '<=': AssertOperator.LE,
}

def check_stress_asserts(task, metrics):
    """校验压测指标是否通过断言"""
    rules = task.get('assert', {})
    if not rules:
        return {'all_pass': True, 'details': []}

    details = []
    all_pass = True

    for assert_name, rule in rules.items():
        if not isinstance(rule, dict):
            continue

        key = rule.get('jsonpath', '').split('.')[-1]  # "$._perf.avg_rt" → "avg_rt"
        actual = metrics.get(key)
        expected = rule.get('value')
        op_enum = _OP_MAP.get(rule.get('type'))
        passed = False
        reason = ''

        if op_enum is None:
            reason = f'未知操作符: {rule.get("type")}'
        elif actual is None:
            reason = f'指标 {key} 不存在'
        else:
            try:
                if op_enum == AssertOperator.EQ:
                    passed = actual == expected
                elif op_enum == AssertOperator.NOT_EQ:
                    passed = actual != expected
                elif op_enum == AssertOperator.GT:
                    passed = float(actual) > float(expected)
                elif op_enum == AssertOperator.GE:
                    passed = float(actual) >= float(expected)
                elif op_enum == AssertOperator.LT:
                    passed = float(actual) < float(expected)
                elif op_enum == AssertOperator.LE:
                    passed = float(actual) <= float(expected)
            except (TypeError, ValueError) as e:
                reason = str(e)

        if not passed and not reason:
            reason = f'expected {op_enum.value} {expected}, got {actual}'
        if not passed:
            all_pass = False

        details.append({
            'name':     assert_name,
            'passed':   passed,
            'actual':   actual,
            'expected': expected,
            'op':       rule.get('type', ''),
            'reason':   reason,
        })

    return {'all_pass': all_pass, 'details': details}

# ============================================================
# 7. 报告输出
# ============================================================

def print_report(task, metrics, assert_result):
    """打印单条用例的压测报告"""
    print(f"\n{'─' * 60}")
    print(f"[{task['name']}] {task.get('detail', '')}")
    print(f"类型: {task['stress_type']}  并发: {task['concurrency']}  "
          f"时长: {task['duration']}s  爬坡: {task['ramp_up']}s")
    print(f"请求: {metrics['total']}  成功: {metrics['success']}  "
          f"失败: {metrics['failed']}  错误率: {metrics['error_rate']}")
    print(f"TPS: {metrics['tps']}  avg: {metrics['avg_rt']}ms  "
          f"P50: {metrics['p50']}ms  P90: {metrics['p90']}ms  P99: {metrics['p99']}ms")
    print(f"min: {metrics['min_rt']}ms  max: {metrics['max_rt']}ms")

    print('断言:')
    for d in assert_result['details']:
        mark = '✓' if d['passed'] else '✗'
        tail = f'  ({d["reason"]})' if d['reason'] else ''
        print(f"  {mark} {d['name']}: 实际={d['actual']} {d['op']} {d['expected']}{tail}")

    result_text = '✅ 全部通过' if assert_result['all_pass'] else '❌ 存在失败'
    print(f'\n结果: {result_text}')

# ============================================================
# 8. 主流程
# ============================================================

def main(yaml_path):
    client = HttpClient()
    tasks = parse_stress_yaml(yaml_path)

    print(f'{"=" * 60}')
    print(f'文件: {yaml_path}')
    print(f'加载 {len(tasks)} 条压测用例')
    print(f'{"=" * 60}')

    summary = []
    try:
        for task in tasks:
            print(f'\n▶ 执行: {task["name"]}')
            t_start = time.time()
            results = run_stress(task, client)
            elapsed = round(time.time() - t_start, 1)
            metrics = calc_metrics(results, task['duration'])
            aresult = check_stress_asserts(task, metrics)
            print_report(task, metrics, aresult)
            print(f'  实际耗时: {elapsed}s')
            summary.append({
                'name':   task['name'],
                'pass':   aresult['all_pass'],
                'tps':    metrics['tps'],
                'avg_rt': metrics['avg_rt'],
                'p99':    metrics['p99'],
                'errors': metrics['error_rate'],
            })
    finally:
        client.close()

    # 汇总
    print(f'\n{"=" * 60}')
    print('汇总')
    print(f'{"用例":<25} {"结果":<8} {"TPS":<10} {"avg":<10} {"P99":<10} {"错误率"}')
    print('─' * 60)
    for s in summary:
        print(f'{s["name"]:<25} {"✓" if s["pass"] else "✗":<8} '
              f'{s["tps"]:<10} {s["avg_rt"]:<10} {s["p99"]:<10} {s["errors"]}')
    print(f'{"=" * 60}')


def run_stress_suite(yaml_path, callback=None, cancel_event=None, pause_event=None):
    """供 Web 后端调用的入口，返回结构化结果

    Args:
        yaml_path: YAML 文件路径
        callback: 可选回调函数，每个用例完成后调用 callback(progress_dict)
        :param yaml_path:
        :param callback:
        :param pause_event:
        :param cancel_event:
    """
    client = HttpClient()
    tasks = parse_stress_yaml(yaml_path)
    summary = []
    try:
        for idx, task in enumerate(tasks):
            t_start = time.time()
            results = run_stress(task, client)
            elapsed = round(time.time() - t_start, 1)
            metrics = calc_metrics(results, task['duration'])
            aresult = check_stress_asserts(task, metrics)
            # ── 暂停检查 ──
            if pause_event and pause_event.is_set():
                if callback:
                    callback({"paused": True, "msg": "压测已暂停"})
                pause_event.wait()  # 阻塞直到 resume 清除
                if callback:
                    callback({"resumed": True, "msg": "压测已恢复"})
            # ── 取消检查 ──
            if cancel_event and cancel_event.is_set():
                if callback:
                    callback({"cancelled": True, "msg": "压测已取消"})
                break
            prog = {
                'done': idx + 1,
                'total': len(tasks),
                'percent': round((idx + 1) / len(tasks) * 100, 1),
                'item': {
                    'name': task['name'],
                    'detail': task.get('detail', ''),
                    'stress_type': task.get('stress_type', ''),
                    'concurrency': task['concurrency'],
                    'duration': task['duration'],
                    'pass': aresult['all_pass'],
                    'metrics': metrics,
                    'assertions': aresult['details'],
                    'elapsed': elapsed,
                },
            }
            if callback:
                callback(prog)
            summary.append(prog['item'])
    finally:
        client.close()
    return {'tasks': len(tasks), 'results': summary}

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('用法: python -m framework.stress_executor <yaml文件路径>\n'
              '      cd framework && python stress_executor.py ../data/xxx.yaml\n'
              '示例: python -m framework.stress_executor data/主播注册接口压测用例_共7条.yaml')
        sys.exit(1)
    main(sys.argv[1])