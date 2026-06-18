import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, r"E:\yebao\test_yaml\test_api")

# 只测试读取Excel和构建api_info部分
try:
    from demo3 import load_excel_cases, build_api_info_from_excel
    
    print("=== 测试 demo3.py 功能 ===\n")
    
    excel_path = r"/data\接口用例数据.xls"
    
    # 测试1: 读取Excel
    print("1. 测试读取Excel的'弹幕'页签...")
    cases = load_excel_cases(excel_path, "弹幕")
    danmu_cases = cases.get("弹幕", [])
    print(f"   成功读取 {len(danmu_cases)} 条用例")
    
    if danmu_cases:
        print(f"\n   第1条用例的键: {list(danmu_cases[0].keys())}")
        print(f"   第1条用例示例: {danmu_cases[0]}")
    
    # 测试2: 构建api_info
    print("\n2. 测试构建api_info...")
    api_info = build_api_info_from_excel(excel_path, "弹幕")
    print(f"   api_info 长度: {len(api_info)} 字符")
    print(f"\n   前300字符内容:")
    print(api_info[:300])
    
    print("\n=== 测试完成 ===")
    print("✅ 功能正常，未发现报错")
    
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 运行出错: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
