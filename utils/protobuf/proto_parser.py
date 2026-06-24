"""Protobuf 二进制 ↔ 字典 转换器（protobuf 6.x+）

用例：
    parser = ProtobufParser()
    parser.load_proto("... text-format FileDescriptorProto ...")
    data = parser.deserialize("mypackage.MyMessage", b"...")
    binary = parser.serialize("mypackage.MyMessage", {"field": "val"})
"""

import google.protobuf.descriptor_pb2 as desc_pb2
from google.protobuf import descriptor_pool, text_format, message_factory
from google.protobuf.json_format import MessageToDict, ParseDict
from typing import Optional, List, Dict, Any


class ProtobufParser:
    """动态 protobuf 解析器 —— 无需预编译 .proto 文件"""

    def __init__(self):
        self.pool = descriptor_pool.DescriptorPool()
        # protobuf 6.x 不暴露内部文件列表，自行维护
        self._loaded_files: List[str] = []

    # ── 加载 proto ────────────────────────────────────────────

    def load_proto(self, proto_content: str, file_name: str = "temp.proto") -> bool:
        """加载 FileDescriptorProto 文本格式到描述符池

        Args:
            proto_content: text-format FileDescriptorProto（非 .proto 源码）
            file_name:      仅用于日志定位

        Returns:
            True 成功; False 失败（错误信息打印到 stderr）
        """
        try:
            fd = desc_pb2.FileDescriptorProto()
            text_format.Parse(proto_content, fd)

            if self._is_loaded(fd.name):
                return True

            self.pool.Add(fd)
            if fd.name not in self._loaded_files:
                self._loaded_files.append(fd.name)
            return True
        except Exception as e:
            print(f"[ProtobufParser] 加载失败: {e}")
            return False

    # ── 描述符查询 ────────────────────────────────────────────

    def get_descriptor(self, full_name: str):
        """获取 message/enum 描述符，找不到返回 None"""
        try:
            return self.pool.FindMessageTypeByName(full_name)
        except KeyError:
            try:
                return self.pool.FindEnumTypeByName(full_name)
            except KeyError:
                return None

    def has_message(self, name: str) -> bool:
        return self.get_descriptor(name) is not None

    def list_messages(self) -> List[str]:
        """列出所有已注册 message 全限定名"""
        result = []
        try:
            for fn in self._loaded_files:
                fd = self.pool.FindFileByName(fn)
                pkg = fd.package + "." if fd.package else ""
                for name in fd.message_types_by_name:
                    result.append(f"{pkg}{name}")
        except Exception:
            pass
        return result

    # ── 反序列化（二进制 → 字典）───────────────────────────────

    def deserialize(self, full_name: str, data: bytes) -> Dict[str, Any]:
        """protobuf 二进制 → dict

        Returns:
            {"data": {...}, "success": True} ｜ {"error": "...", "success": False}
        """
        try:
            desc = self.get_descriptor(full_name)
            if desc is None:
                return {"error": f"message 不存在: {full_name}", "success": False}

            msg_cls = message_factory.GetMessageClass(desc)
            msg = msg_cls()
            msg.ParseFromString(data)

            return {
                "data": MessageToDict(msg, preserving_proto_field_name=True),
                "success": True,
            }
        except Exception as e:
            return {"error": str(e), "success": False}

    # ── 序列化（字典 → 二进制）─────────────────────────────────

    def serialize(self, full_name: str, data_dict: Dict[str, Any]) -> bytes:
        """dict → protobuf 二进制

        Raises:
            ValueError: message 不存在
            Exception:  序列化错误
        """
        try:
            desc = self.get_descriptor(full_name)
            if desc is None:
                raise ValueError(f"message 不存在: {full_name}")

            msg_cls = message_factory.GetMessageClass(desc)
            msg = msg_cls()

            # protobuf 不接受 None 值
            clean = {k: v for k, v in data_dict.items() if v is not None}

            # protobuf 6.x 已移除 preserving_proto_field_name
            ParseDict(clean, msg)
            return msg.SerializeToString()
        except ValueError:
            raise
        except Exception as e:
            raise type(e)(f"[ProtobufParser] {e}") from e

    # ── 内部 ──────────────────────────────────────────────────

    def _is_loaded(self, file_name: str) -> bool:
        try:
            self.pool.FindFileByName(file_name)
            return True
        except KeyError:
            return False
