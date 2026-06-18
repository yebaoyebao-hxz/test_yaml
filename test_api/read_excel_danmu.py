import xlrd
import sys
import json

# 读取Excel文件
excel_path = r"/data\接口用例数据.xls"

try:
    book = xlrd.open_workbook(excel_path)
    print("所有sheet名称:", book.sheet_names())
    
    # 读取"弹幕" sheet
    if u"弹幕" in book.sheet_names():
        sheet = book.sheet_by_name(u"弹幕")
        print(f"\n=== 弹幕 sheet 信息 ===")
        print(f"行数: {sheet.nrows}")
        print(f"列数: {sheet.ncols}")
        
        # 读取表头（第1行）
        headers = sheet.row_values(0)
        print(f"\n表头（第1行):")
        for i, h in enumerate(headers):
            print(f"  {i}: {h}")
        
        # 读取前3行数据
        print(f"\n前3行数据示例:")
        for r in range(1, min(4, sheet.nrows)):
            print(f"\n第{r+1}行:")
            row = sheet.row_values(r)
            for i, h in enumerate(headers):
                if i < len(row):
                    print(f"  {h}: {row[i]}")
    else:
        print("未找到'弹幕' sheet")
        
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
