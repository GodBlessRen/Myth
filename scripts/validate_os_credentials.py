"""系统凭据库容量/轮转/清理 smoke。
仅使用随机独立 service 与合成字符串，不读取用户账号；系统库写入必须通过明确 --allow-os-store 开关。
"""

import argparse
import json
import uuid

from myth.auth.chatgpt import KeyringCredentialStore


# 用随机 service 验证超过单条上限的合成记录，finally 删除全部分块并核对不存在。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-os-store", action="store_true")
    args = parser.parse_args()
    store = KeyringCredentialStore("Myth synthetic audit " + uuid.uuid4().hex)
    backend = store._backend()
    result = {"backend": type(backend).__module__ + "." + type(backend).__name__, "synthetic_only": True}
    if not args.allow_os_store:
        print(json.dumps(result))
        return
    profile = "synthetic_audit_" + uuid.uuid4().hex
    first = {"access_token": "synthetic-access-" * 1000, "refresh_token": "synthetic-refresh-" * 400,
        "id_token": "synthetic-id-" * 600}
    second = {**first, "access_token": "synthetic-rotated-" * 1000}
    try:
        store.save(profile, first)
        if store.load(profile) != first:
            raise RuntimeError("synthetic credential round trip differs")
        store.save(profile, second)
        if store.load(profile) != second:
            raise RuntimeError("synthetic credential rotation differs")
        result.update(round_trip=True, rotated=True, payload_bytes=len(json.dumps(second).encode()))
    finally:
        store.delete(profile)
    if store.load(profile) is not None:
        raise RuntimeError("synthetic credential cleanup is incomplete")
    result["deleted"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    main()
