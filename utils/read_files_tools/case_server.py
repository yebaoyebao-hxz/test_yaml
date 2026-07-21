from flask import Flask, request, jsonify
import os
import base64
from yaml_func_case_generator import generate_text_func, generate_image_func, generate_mixed_func

app = Flask(__name__)
# 临时图片缓存目录
TMP_IMG = "./tmp_upload"

os.makedirs(TMP_IMG, exist_ok = True)

# 1. 纯文本生成接口
@app.post("/api/case/generate_text")
def api_text():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"success": False, "error": "功能描述不能为空"})
    res = generate_text_func(text)
    return jsonify(res.to_dict())

# 2. 单图片 + 描述生成
@app.post("/api/case/generate_img")
def api_img():
    desc = request.form.get("text", "")
    img_file = request.files.get("image")
    if not img_file:
        return jsonify({"success": False, "error": "请上传截图"})
    # 保存临时文件
    save_path = os.path.join(TMP_IMG, img_file.filename)
    img_file.save(save_path)
    res = generate_image_func(save_path, desc)
    return jsonify(res.to_dict())

# 3. 多图+文本混合生成
@app.post("/api/case/generate_mixed")
def api_mixed():
    text = request.form.get("text", "")
    img_list = request.files.getlist("images")
    if len(img_list) == 0:
        return jsonify({"success": False, "error": "至少上传一张截图"})
    paths = []
    for f in img_list:
        p = os.path.join(TMP_IMG, f.filename)
        f.save(p)
        paths.append(p)
    res = generate_mixed_func(text, paths)
    return jsonify(res.to_dict())

if __name__ == "__main__":
    # 端口5000启动，前端跨域可加flask-cors
    from flask_cors import CORS
    CORS(app)
    app.run(host="0.0.0.0", port=5000, debug=True)