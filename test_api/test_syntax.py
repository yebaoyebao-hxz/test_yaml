import sys
import py_compile

try:
    py_compile.compile(r"E:\yebao\test_yaml\test_api\demo3.py", doraise=True)
    print("✅ demo3.py 语法检查通过")
    sys.exit(0)
except py_compile.PyCompileError as e:
    print(f"❌ 语法错误: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 其他错误: {e}")
    sys.exit(1)
