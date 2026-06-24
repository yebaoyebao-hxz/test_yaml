# -*- coding: utf-8 -*-
"""Protobuf 可视化调试 — Flask Blueprint"""
import sys, os
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from flask import Blueprint, request, jsonify
from utils.protobuf.proto_parser import ProtobufParser

proto_bp = Blueprint("protobuf", __name__)

parser = ProtobufParser()


@proto_bp.route("/api/proto/load", methods=["POST"])
def api_proto_load():
    """加载 FileDescriptorProto 文本到解析器"""
    body = request.get_json(force=True) or {}
    proto_text = body.get("proto_text", "").strip()
    file_name = body.get("file_name", "temp.proto")

    if not proto_text:
        return jsonify({"success": False, "error": "proto_text 不能为空"}), 400

    ok = parser.load_proto(proto_text, file_name)
    return jsonify({
        "success": ok,
        "error": "" if ok else "加载失败，查看服务端控制台"
    })


@proto_bp.route("/api/proto/messages", methods=["GET"])
def api_proto_messages():
    """列出已加载的所有 message"""
    msgs = parser.list_messages()
    return jsonify({"success": True, "messages": msgs})


@proto_bp.route("/api/proto/deserialize", methods=["POST"])
def api_proto_deserialize():
    """二进制 → dict（前端传 base64 编码的二进制数据）"""
    body = request.get_json(force=True) or {}
    message_name = body.get("message_name", "").strip()
    binary_b64 = body.get("binary_data", "").strip()

    if not message_name or not binary_b64:
        return jsonify({"success": False, "error": "message_name 和 binary_data 不能为空"}), 400

    import base64
    try:
        raw = base64.b64decode(binary_b64)
    except Exception as e:
        return jsonify({"success": False, "error": f"Base64 解码失败: {e}"}), 400

    result = parser.deserialize(message_name, raw)
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error", "反序列化失败")}), 400

    return jsonify({"success": True, "data": result["data"]})


@proto_bp.route("/api/proto/deserialize-hex", methods=["POST"])
def api_proto_deserialize_hex():
    """二进制 → dict（前端传 hex 字符串）"""
    body = request.get_json(force=True) or {}
    message_name = body.get("message_name", "").strip()
    hex_str = body.get("hex_data", "").strip()

    if not message_name or not hex_str:
        return jsonify({"success": False, "error": "message_name 和 hex_data 不能为空"}), 400

    try:
        raw = bytes.fromhex(hex_str)
    except Exception as e:
        return jsonify({"success": False, "error": f"Hex 解码失败: {e}"}), 400

    result = parser.deserialize(message_name, raw)
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("error", "反序列化失败")}), 400

    return jsonify({"success": True, "data": result["data"]})


@proto_bp.route("/api/proto/serialize", methods=["POST"])
def api_proto_serialize():
    """dict → 二进制（返回 hex + base64）"""
    body = request.get_json(force=True) or {}
    message_name = body.get("message_name", "").strip()
    data_dict = body.get("data", {})

    if not message_name:
        return jsonify({"success": False, "error": "message_name 不能为空"}), 400

    import base64
    try:
        raw = parser.serialize(message_name, data_dict)
        return jsonify({
            "success": True,
            "hex": raw.hex(),
            "base64": base64.b64encode(raw).decode(),
            "size": len(raw)
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@proto_bp.route("/api/proto/clear", methods=["POST"])
def api_proto_clear():
    """清空已加载的 proto"""
    global parser
    parser = ProtobufParser()
    return jsonify({"success": True, "message": "已清空"})
