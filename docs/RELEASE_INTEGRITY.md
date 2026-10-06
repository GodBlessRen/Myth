# 发布完整性合同

`scripts/validate_release.py` 以脚本所在 checkout 为基准，只读归档，不解压到磁盘、不执行归档内容。它核对当前文件，不把归档自己的 RECORD、SOURCES.txt 或名称列表当作可信基准。

## 检查范围

| 产物 | 必须存在且内容一致的文件 | 拒绝的额外内容 |
| --- | --- | --- |
| wheel | `src/myth/` 下全部非缓存普通文件，映射为 `myth/` | 旧模块、任意后缀旧资源、额外顶层载荷及 `.data` 重定位入口；只允许包与 `.dist-info` 元数据 |
| sdist | 同上，加完整 `scripts/`、`tests/`、`pyproject.toml`、`MANIFEST.in`，以及当前存在的 setup 配置 | 旧脚本/测试、额外 src 包、当前不存在的 setup 配置、错误的顶层位置 |
| Git ZIP | 与 sdist 相同，可无顶层前缀或恰好一层前缀 | 同上；分散在多个包根的文件不能拼凑通过 |

`MANIFEST.in` 完整收录包、脚本和测试，因此 `check_web.cjs`、PNG 来源 JSON、字体及许可说明不再依赖另一份扩展名名单。归档中的缺失、多余文件、大小差异或同长度 SHA-256 差异均使检查失败。

源码基准的包入口、Web 入口和源码门禁缺失会拒绝检查；基准中的链接与私有数据也不能被当成正常源码。该合同依赖调用者提供完整、可信的 checkout，不能证明 checkout 本身未被删除或恶意修改。

## 字节与平台边界

wheel/sdist 严格比较工作树原字节。Git ZIP 在有本地 Git 证据时，仅对索引为 LF、工作树为统一 LF/CRLF 的已知文本允许这两种换行编码；这覆盖 Git 导出的 `core.eol` 差异。内容、空格、编码和混合换行没有通用豁免；字体、图片和未知二进制始终逐字节核对。没有 Git 证据时严格比较原字节。

返回 `verified_files`、`verified_bytes` 和 `git_eol_files`，最后一项记录实际使用换行等价的文件数。先核对声明大小，再按块读取同一已验证归档句柄，避免为明显错误的载荷进行无界解压。

路径规则保留：拒绝上溯、绝对路径、反斜杠、NUL/控制字符、Windows 设备名/尾空格/尾句点、大小写冲突、重复路径、文件/目录冲突，以及链接、硬链接和设备。任意层的 `.trash`、`.work`、`.work-notes`、运行数据、私有配置/密钥/数据库文件均拒绝；错误只给路径和失败类型，不回显内容。

## 验证与范围限制

针对性测试覆盖缺文件、同名变字节、未知资源扩展、陈旧载荷、门禁错根、构建入口注入、原有路径攻击、真实临时 Git 导出与 LF/CRLF 双向差异。`test_release_integrity.py` 另用完整真实当前文件构造合成 wheel/sdist 样本；这些样本不是构建或安装证据。

真实发布仍需干净构建后运行 `python scripts/validate_release.py dist`，再在独立安装目录执行 `scripts/validate_package.py`。本检查不验证生成元数据的语义、依赖解析、安装/HTTP 行为、所有类型的凭据或供应链真实性；文档、示例与评测数据不在逐字节完整性分母内。已知秘钥模式继续由 `scripts/audit_secret_patterns.py` 独立检查。
