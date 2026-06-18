import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 测试 demo3 的功能（不调用AI）
sys.path.insert(0, r"E:\yebao\test_yaml\test_api")

try:
    # 只导入需要的函数，不调用AI
    from demo3 import load_excel_cases, build_api_info_from_excel
    
    print("=== 测试 demo3.py 功能 ===\n")
    
    # 1. 测试读取Excel
    excel_path = r"/data\接口用例数据.xls"
    print("1. 测试读取Excel的'弹幕'页签...")
    
    cases = load_excel_cases(excel_path, "弹幕")
    danmu_cases = cases.get("弹幕", [])
    print(f"   成功读取 {len(danmu_cases)} 条用例")
    
    if danmu_cases:
        print(f"\n   第1条用例示例:")
        first_case = danmu_cases[0]
        for key, val in first_case.items():
            print(f"     {key}: {val}")
    
    # 2. 测试构建 api_info
    print("\n\n2. 测试构建 api_info...")
    api_info = build_api_info_from_excel(excel_path, "弹幕")
    
    print(f"   api_info 构建完成，长度: {len(api_info)} 字符")
    print(f"\n   前500字符内容:")
    print(api_info[:500])
    
    print("\n\n=== 测试完成 ===")
    print("✅ Excel读取功能正常")
    print("✅ api_info构建功能正常")
    print("\n提示: 要测试完整的AI生成功能，需要提供有效的 DeepSeek API Key")
    
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
