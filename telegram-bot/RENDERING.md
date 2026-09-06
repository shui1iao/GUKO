# Check.Place Pillow 绘图

保留 GUKO 高对比度 FG/BG 配色及中文双格对齐，不改用浏览器。
默认网格为 14×28 px、字号 28 px，即源 SVG 的 7px 字宽 / 14px em 的两倍。
IPQuality 没有 xyBarMono 声明，也使用相同双格约定，避免中文错位。
Latin 依据字体 advance 横向适配单格；中文保持双格。字形侧边距和共同 baseline
不随每个字的墨迹 bbox 重新居中。文字与高亮共用网格，矩形使用半开区间。
超出 SVG 声明宽度的文本/背景会扩展画布；斜体和重音的边缘墨迹不裁切。

- Latin 使用 DejaVu Sans Mono 的 Regular、Bold、Oblique、BoldOblique。
- 中文使用 Noto Sans CJK Regular/Bold，斜体在共同 baseline 上做水平 shear。
- SVG 行首换行按保留空白规则转为一格空格，CRLF 只计一次；不能删除，
  原始高亮坐标包含这一格。空 `class=""` 的 tspan 同样保留内容。
- Dockerfile 使用系统字体包，并在构建时实际加载全部所需字面；无需运行时下载。

## 私有原图形字体（可选）

源报告字体：<https://res.check.place/fonts/xyBarMono.woff>
其内嵌 name 表声明：

> Owned by xykt@GitHub
>
> Free to Display, Development or Commercial Use Requires Authorization

本项目不重新许可、不公开分发该字体。不要把 WOFF、转换后的 TTF 或私有字体
放入公开仓库/镜像；使用前自行确认适用授权。需要原报告图形时，可在获得适用
授权的私有环境中提供保留原元数据的 TTF，通过只读挂载使用，例如：

```yaml
# 添加到现有 bot 服务，不是独立 compose 文件
volumes:
  - /opt/guko/fonts:/data/fonts:ro
environment:
  CHECKPLACE_GRAPH_FONT: /data/fonts/xyBarMono.ttf
```

仅在 SVG 声明 xyBarMono 时使用该文件，且仅用于它实际含有的盲文柱形、框线和
U+2714/U+2718（✔/✘）。缺失字符回退，不能把稀疏字体强行用于中文或所有 Unicode。
未配置时会给出明确警告，继续使用系统字体；通用盲文点阵不等同于原柱形。
若显式配置了损坏/不存在的字体路径则加载失败，避免静默假称恢复原图。

## 本地测试

在具有镜像系统字体和 Python 依赖的环境执行：

```sh
python -m unittest discover -s tests -v
CHECKPLACE_GRAPH_FONT=/private/path/xyBarMono.ttf python -m unittest discover -s tests -v
```

前者跳过两项私有原字体像素测试；后者执行全部测试。测试不下载字体，也不运行 bot。
本绘图器处理 Check.Place 固定格式的终端 SVG 子集，不是通用 SVG/CSS 渲染引擎。
