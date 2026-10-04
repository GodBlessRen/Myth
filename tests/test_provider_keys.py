"""回归边界：应用内 Provider API Key 安全存储与兼容回退。
固定内存凭据替身只验证 Myth 的状态/优先级/删除语义，不代表真实 OS keyring 或远端 Provider 可用。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from myth.auth.provider_keys import ProviderApiKeyVault


# 内存凭据替身；只实现 ProviderApiKeyVault 依赖的 load/save/delete 端口。
class MemoryCredentialStore:
    def __init__(self):
        self.values = {}

    def load(self, profile_id):
        value = self.values.get(profile_id)
        return dict(value) if value else None

    def save(self, profile_id, value):
        self.values[profile_id] = dict(value)

    def delete(self, profile_id):
        self.values.pop(profile_id, None)


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
