"""本地 Skill 的发现与分页读取适配器。
只读取 .myth/skills/<id>/SKILL.md；流程是可参考的任务资料，不装载脚本或修改工具权限。"""

import re

from ..domain import sha256_bytes
from .extension_config import EXTENSION_ID, LocalExtensionConfig


class LocalSkillLibrary:
    """固定根内的只读资源库；摘要绑定完整文件，模型只拿到有界元数据和分页正文。"""

    def __init__(self, config: LocalExtensionConfig):
        """绑定只读扩展配置边界；构造阶段不读取 Skill 正文或扩大任何能力。"""
        # config：目录边界的唯一协作者；不借用项目路径或用户可编辑的会话字段。
        self.config = config

    def _read(self, skill_id: str) -> tuple[str, str]:
        """读取最多 64 KiB 的 UTF-8 Skill，拒绝链接、越界、无效身份和二进制文本。"""
        if not isinstance(skill_id, str) or not EXTENSION_ID.fullmatch(skill_id):
            raise ValueError("skill_id must be one portable directory name")
        path = self.config.checked_path(f"skills/{skill_id}/SKILL.md")
        if not path.is_file():
            raise ValueError("skill resource does not exist")
        try:
            with path.open("rb") as stream:
                raw = stream.read(65537)
        except OSError:
            raise ValueError("skill resource is unavailable") from None
        if len(raw) > 65536:
            raise ValueError("SKILL.md exceeds 64 KiB")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError:
            raise ValueError("SKILL.md must be UTF-8") from None
        if "\0" in text:
            raise ValueError("SKILL.md must be text")
        return text, sha256_bytes(raw)

    @staticmethod
    def _metadata(text: str, skill_id: str) -> dict:
        """提取简易 name/description 字段或 Markdown 首行；不是通用 YAML 解释器。"""
        lines = text.splitlines()
        header, body = [], lines
        if lines and lines[0].strip() == "---":
            end = next((i for i, line in enumerate(lines[1:65], 1) if line.strip() == "---"), None)
            if end is not None:
                header, body = lines[1:end], lines[end + 1:]
        values = {}
        for line in header:
            match = re.fullmatch(r"(name|description):\s*(.*)", line)
            if match:
                value = match[2].strip().strip("\"'")
                if value not in {"|", ">", "|-", ">-"}:
                    values[match[1]] = value
        fallback = next((line.strip().lstrip("# ") for line in body if line.strip()), skill_id)
        return {"name": values.get("name", skill_id)[:100],
                "description": values.get("description", fallback)[:500]}

    def list_skills(self) -> dict:
        """列出最多 128 个技能；坏资源显式标为不可用，不把目录错误解释为成功加载。"""
        root = self.config.checked_path("skills")
        if not root.exists():
            return {"skills": [], "unavailable": [], "truncated": False}
        rows, unavailable = [], []
        entries = sorted(root.iterdir(), key=lambda item: item.name)
        for directory in entries[:128]:
            if not EXTENSION_ID.fullmatch(directory.name):
                continue
            try:
                text, digest = self._read(directory.name)
                rows.append({"skill_id": directory.name, **self._metadata(text, directory.name),
                             "digest": digest, "chars": len(text), "source_kind": "skill_resource"})
            except (ValueError, PermissionError, OSError):
                unavailable.append({"skill_id": directory.name, "reason": "resource_unavailable"})
        return {"skills": rows, "unavailable": unavailable, "truncated": len(entries) > 128}

    def load(self, skill_id: str, expected_digest: str, offset: int = 0, max_chars: int = 12000) -> dict:
        """按已发现全文摘要分页；零偏移有效，资源变化明确要求重新 list。"""
        if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 1 <= max_chars <= 12000:
            raise ValueError("skill pagination requires offset >= 0 and max_chars 1-12000")
        text, digest = self._read(skill_id)
        if expected_digest != digest:
            raise ValueError("skill digest changed; call skill.list again")
        if offset > len(text):
            raise ValueError("skill offset exceeds resource length")
        end = min(len(text), offset + max_chars)
        return {"skill_id": skill_id, "digest": digest, **self._metadata(text, skill_id),
                "content": text[offset:end], "offset": offset, "next_offset": end if end < len(text) else None,
                "total_chars": len(text), "source_kind": "skill_resource", "grants_capabilities": False}
