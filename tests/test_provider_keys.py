"""回归边界：应用内 Provider API Key 安全存储与兼容回退。
固定内存凭据替身只验证 Myth 的状态/优先级/删除语义，不代表真实 OS keyring 或远端 Provider 可用。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from myth.auth.provider_keys import ProviderApiKeyVault


# 内存凭据替身；只实现 ProviderApiKeyVault 依赖的 load/save/delete 端口。
# API Key 安全库的内存替身；只保存本测试进程内字典，不模拟系统 keyring 的安全属性。
class MemoryCredentialStore:
    # 建立每个测试独立的凭据字典；测试结束即销毁，不能代表生产持久存储。
    def __init__(self):
        # values：测试替身内部凭据；断言只验证调用语义，绝不写入 Runtime。
        self.values = {}

    # 按 provider/profile 身份读取测试凭据副本，避免调用方修改替身内部状态。
    def load(self, profile_id):
        value = self.values.get(profile_id)
        return dict(value) if value else None

    # 保存测试凭据副本；只模拟 CredentialStore 端口，不声称安全持久化。
    def save(self, profile_id, value):
        self.values[profile_id] = dict(value)

    # 幂等删除测试凭据；用于核对断开连接不影响其他 provider。
    def delete(self, profile_id):
        self.values.pop(profile_id, None)


# 应用内 Provider API Key 的固定回归集合；验证秘钥边界、优先级与兼容迁移。
class ProviderApiKeyVaultTests(unittest.TestCase):
    # 应用内保存后状态只暴露来源，不返回 key 或其片段。
    def test_save_resolve_and_status_never_echo_secret(self):
        store = MemoryCredentialStore()
        vault = ProviderApiKeyVault(store=store)
        secret = "sk-super-secret-value"
        status = vault.save("openai", secret)
        value, source = vault.resolve("openai")

        self.assertEqual(value, secret)
        self.assertEqual(source, "myth")
        self.assertTrue(status["configured"])
        self.assertNotIn(secret, str(status))
        public = vault.status("openai")
        self.assertNotIn(secret, str(public))
        self.assertEqual(public["source"], "myth")

    # Myth 安全库优先于旧环境变量；迁移用户无需先清理 PowerShell 配置。
    def test_myth_key_wins_over_environment_compatibility(self):
        store = MemoryCredentialStore()
        vault = ProviderApiKeyVault(store=store)
        vault.save("deepseek", "myth-deepseek-key")
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "legacy-env-key"}):
            value, source = vault.resolve("deepseek")
        self.assertEqual(value, "myth-deepseek-key")
        self.assertEqual(source, "myth")

    # 没有应用内 key 时仍兼容旧环境变量；这只是迁移回退，不是新用户必经步骤。
    def test_environment_remains_compatibility_fallback(self):
        vault = ProviderApiKeyVault(store=MemoryCredentialStore())
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-openai-key"}, clear=True):
            value, source = vault.resolve("openai")
            status = vault.status("openai")
        self.assertEqual(value, "legacy-openai-key")
        self.assertEqual(source, "environment")
        self.assertEqual(status["source"], "environment")

    # 删除 Myth 管理的 key 后不删除进程外环境配置；网页不能越权修改外部 shell 状态。
    def test_delete_only_removes_myth_managed_secret(self):
        store = MemoryCredentialStore()
        vault = ProviderApiKeyVault(store=store)
        vault.save("openai", "myth-openai-key")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "legacy-openai-key"}, clear=True):
            status = vault.delete("openai")
            value, source = vault.resolve("openai")
        self.assertEqual(value, "legacy-openai-key")
        self.assertEqual(source, "environment")
        self.assertEqual(status["source"], "environment")


if __name__ == "__main__":
    unittest.main()
