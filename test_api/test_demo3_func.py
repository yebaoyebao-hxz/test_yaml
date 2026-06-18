import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

sys.path.insert(0, r"E:\yebao\test_yaml\test_api")

try:
    # 测试导入
    from demo3 import load_excel_cases, build_api_info_from_excel, save_generated_cases_to_file
    print("✅ demo3.py 导入成功\n")
    
    # 测试1: 读取Excel
    excel_path = r"/data\接口用例数据.xls"
    print("1. 测试读取Excel的'弹幕'页签...")
    
    cases = load_excel_cases(excel_path, "弹幕")
    danmu_cases = cases.get("弹幕", [])
    print(f"   成功读取 {len(danmu_cases)} 条用例")
    
    if danmu_cases:
        print(f"\n   第1条用例的键: {list(danmu_cases[0].keys())}")
        print(f"   第1条用例内容:")
        for key, val in danmu_cases[0].items():
            print(f"     {key}: {val}")
    
    # 测试2: 构建api_info
    print("\n\n2. 测试构建api_info...")
    api_info = build_api_info_from_excel(excel_path, "弹幕")
    
    print(f"   api_info 长度: {len(api_info)} 字符")
    print(f"\n   前500字符内容:")
    print(api_info[:500])
    
    print("\n\n=== 测试完成 ===")
    print("✅ Excel读取功能正常")
    print("✅ api_info构建功能正常")
    print("\n提示: 要测试完整的AI生成功能，需要:")
    print("  1. 提供有效的 DeepSeek API Key")
    print("  2. 在 api_config.py 中配置")
    print("  3. 调用 generate_api_cases 函数")
    
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
