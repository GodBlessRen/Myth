# 工作台离线字体

三个 WOFF2 随 wheel 分发，所有浏览器请求来自本机；不会访问 Google Fonts。

| 文件 | 上游 | 范围 |
| --- | --- | --- |
| myth-sans.woff2 | [Noto Sans SC](https://github.com/google/fonts/tree/main/ofl/notosanssc) | 上游完整 Unicode 字符表；工作台 400–650 字重 |
| myth-serif.woff2 | [Noto Serif SC](https://github.com/google/fonts/tree/main/ofl/notoserifsc) | 静态界面标题字形；其他字形回退正文 |
| myth-latin.woff2 | [Manrope](https://github.com/google/fonts/tree/main/ofl/manrope) | 拉丁字符，400–650 字重 |

使用 SIL Open Font License 1.1，三个原始 OFL 文件随包保留。CSS 家族别名不改变字体内部身份。

重建：下载官方 TTF 为 `.runtime/font-sources/{sans,serif,manrope}.ttf`，安装 `fonttools[woff]`，运行 `python scripts/build_ui_fonts.py`。原始 TTF 与构建依赖不进入应用包；标题文案改变后重新构建宋体子集。
