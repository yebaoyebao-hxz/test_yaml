import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

try:
    # 直接导入 demo3 模块检查语法
    sys.path.insert(0, r"E:\yebao\test_yaml\test_api")
    
    # 检查语法
    import py_compile
    py_compile.compile(r"E:\yebao\test_yaml\test_api\demo3.py", doraise=True)
    print("✅ demo3.py 语法检查通过")
    
except SyntaxError as e:
    print(f"❌ 语法错误在第 {e.lineno} 行: {e.msg}")
    print(f"   错误内容: {e.text}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 其他错误: {e}")
    sys.exit(1)
