"""构建工作台离线字体；输入是 Google Fonts 的原始字体，输出属于静态 Adapter。

运行前将 Noto Sans SC、Noto Serif SC、Manrope 的 TTF 放入 .runtime/font-sources。
保留正文完整字符表；标题只收录静态界面用字，其他标题字形回退到正文字体。
字体不参与业务状态；OFL 授权文件必须与输出一起打包。
"""

from pathlib import Path
import sys

# 项目临时压缩依赖不改变用户 Python 环境，也不进入生产包。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".runtime/font-tooling"))

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


def main() -> None:
    """以完整正文、静态标题和拉丁文字三种范围生成 WOFF2；保留字重轴。"""
    source = ROOT / ".runtime/font-sources"
    destination = ROOT / "src/myth/webui/fonts"
    heading_text = "".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/myth/webui").glob("*.html")
    ) + "有什么想推进的？开始一件事。新的对话工作空间Myth"
    for name, output, text in (
        ("sans", "myth-sans.woff2", None),
        ("serif", "myth-serif.woff2", heading_text),
        ("manrope", "myth-latin.woff2", "".join(chr(code) for code in range(32, 256))),
    ):
        font = TTFont(source / f"{name}.ttf")
        # 限制工作台使用的字重范围，正文保留全部 Unicode 字形与真实可变字重。
        options = subset.Options()
        options.flavor = "woff2"
        options.layout_features = ["*"]
        options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14, 16, 17]
        cutter = subset.Subsetter(options=options)
        cutter.populate(unicodes=font.getBestCmap() if text is None else set(map(ord, text)))
        cutter.subset(font)
        instantiateVariableFont(font, {"wght": (400, 400, 650)}, inplace=True)
        font.flavor = "woff2"
        font.save(destination / output)
        print(f"{output}: {(destination / output).stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
