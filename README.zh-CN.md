<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

# lookmatch

[![CI](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml/badge.svg)](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml)

给 lookmatch 一张或几张你喜欢的调色照片，再加上一个装着你自己照片的文件夹。它会测量两边的颜色，生成一个 LUT，让你这台相机拍的照片都能呈现同样的色调，包括你以后拍的照片。你会得到可以在 Lightroom、Photoshop、DaVinci Resolve 等软件里使用的 LUT 和预设。

> **当前状态：** 早期开发中。你可以[试用](#试用)，但还不够完善。整套引擎已经完成并通过测试，lookmatch 生成的 LUT 在 Photoshop 和 DaVinci Resolve 里的效果完全一致。当参考照片和你的照片拍的是相同或相似的场景时，色调匹配得很准；当两边场景不同时，它只学习可靠的部分（黑白点和色调偏色），其余保持不变，详见[基准测试](#基准测试)。欢迎 Star 关注进展。

## 基于测量，而不是猜测

- **每一个数值都来自测量或优化。** 没有任何 AI 模型去决定滑块数值、曲线或 LUT 的颜色。lookmatch 测量你的照片和参考照片中的颜色，然后计算出两者之间的变化。
- **同样的照片，同样的结果。** 随机采样使用固定的种子，每次运行结果完全一致，可以复现。
- **每一步都经过验证。** 引擎的每个部分都用已知答案和独立的第三方库进行测试，每次修改都会自动重新检查。
- **方法来自已发表的色彩科学研究**，引用见 [docs/method.md](docs/method.md)（英文）。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/pipeline_dark.svg">
  <img alt="六个步骤：读取、中性化、测量色调、生成 3D LUT、验证、导出。" src="docs/figures/pipeline_light.svg" width="100%">
</picture>

## 看看引擎的效果

下面的图用一个**手工制作的测试色调**来检验引擎：暗部偏暖、亮部偏冷，再加一条柔和的 S 曲线。所有图都由 lookmatch 自己计算生成（[docs/figures/make_figures.py](docs/figures/make_figures.py)）。

**测试色调做了什么（实测）。** 一条从黑到白的灰阶经过这个 LUT，lookmatch 在 OKLab 中测量结果。OKLab 是一种按照人眼感知颜色差异来设计的色彩空间。

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/tone_response_dark.svg">
  <img alt="折线图。暗部的暖度提高约 2 个 OKLab 单位，亮部降低约 2.5。暗部亮度最多降低 3，亮部最多提高 3。纯黑和纯白保持不变。" src="docs/figures/tone_response_light.svg" width="100%">
</picture>

**从照片中学习色调。** 左：你的照片（相机直出的 JPEG）。中：目标色调。右：lookmatch 用默认设置从参考照片中学到的色调，套用在你的照片上。上排：明亮通透的日系清新风格（暗部提亮、反差柔和、色彩淡雅、高光偏冷）。下排：浓郁的青橙色调。

<img alt="费城市政厅，两排各三张。上排：原图；暗部提亮、带青色调的淡雅日系版本；lookmatch 的结果，与目标几乎完全一样。下排：原图；天空深青、暗部偏青、石材偏暖的青橙版本；lookmatch 的结果，与目标几乎完全一样。" src="docs/figures/photo_match.jpg" width="100%">

| 色调 | 目标与原图之差 | lookmatch 与目标之差 |
|---|---|---|
| 日系清新 | ΔE 11.6 | **ΔE 0.3**（三张示例照片都是 0.3） |
| 青橙 | ΔE 6.6 | **ΔE 0.8**（三张都约为 0.8） |

ΔE 2000 衡量人眼可见的色差：低于约 1 时看不出差别，2 到 3 时并排对比勉强能看出。两个色调都由 lookmatch 自己的公式生成（[bench/make_looks.py](bench/make_looks.py)），不是取自任何人的预设。这是**最简单的情况**：参考照片是同一次拍摄的三张照片套用色调后的结果，就像你修好了自己的几张照片，想让其余照片保持一致。当参考照片拍的是其他场景时，效果没有这么精确（见[基准测试](#基准测试)）。保护肤色的人像示例即将加入。

**用在测试色卡上。** 灰阶、24 色 ColorChecker 色卡和纯原色，左为原图，右为套用后。

<img alt="测试色卡套用测试色调前后对比。" src="docs/figures/chart_before_after.png" width="100%">

**在你的软件里效果一样。** 把同一个 LUT 在 Photoshop 和 DaVinci Resolve 中套用到测试色卡上，测量全部 69 个色块：Photoshop 与 lookmatch 完全一致，Resolve 的差异在 1/255 以内（[结果](bench/APP_CHECK_RESULTS.md)）。

## 试用

lookmatch 还没有发布到 PyPI。现在想试用，需要 Python 3.11 或更新版本：

```bash
git clone https://github.com/ShadowSkeleton/lookmatch.git
cd lookmatch
python3 -m venv .venv
.venv/bin/pip install -e .
```

把几张有你想要色调的照片放进一个文件夹，再把至少 5 张你自己未经调色的照片放进另一个文件夹，然后运行：

```bash
.venv/bin/lookmatch fit ~/Pictures/look-i-love ~/Pictures/my-photos --name "日系清新"
```

lookmatch 只读取你的照片，绝不修改。它会新建一个文件夹 `日系清新/`：

| 文件 | 内容 |
|---|---|
| `report.html` | 先打开这个：你的照片套用前后对比、这个色调做了什么、需要注意的地方 |
| `日系清新_33.cube` | 色调 LUT，用于 Photoshop、DaVinci Resolve 和大多数软件 |
| `日系清新_hald.png` | 图片格式的同一个 LUT，用于 RawTherapee 和 darktable |
| `日系清新_preset.xmp` | 可编辑的 Lightroom / Camera Raw 预设（接近原色调，但不完全一样） |
| `LIGHTROOM_PROFILE.md` | 在 Lightroom 里使用完整色调的步骤 |
| `look.json` | lookmatch 测量到的全部数据，可完全复现这个色调 |
| `previews/` | 套用色调后的你的照片 |

如果照片里有人物，加上 `--portrait`，让肤色保持自然。各软件的详细使用步骤见 [docs/apps.md](docs/apps.md)（英文）。

## 如何测试

| 测试内容 | 对照标准 | 容差 |
|---|---|---|
| sRGB、线性和 OKLab 之间的转换 | 10,000 个数值来回转换 | 0.0001 |
| OKLab 数值 | colour-science（独立的第三方库） | 0.002 |
| 手机拍的 Display P3 照片 | colour-science 的转换结果 | 2/255 |
| `.cube` LUT 文件 | 写入后再读回 | 完全一致 |
| 套用 LUT | SciPy 的插值结果 | 0.000000000001 |
| 同一个 LUT 在 Photoshop 和 Resolve 中 | lookmatch 自己的结果，69 个色块 | 0 和 1/255 |
| 色差（ΔE 2000） | 已发表的测试数据（Sharma 等，2005） | 0.0001 |
| 还原已知的影调曲线 | 合成照片 | 0.41% |

每次修改都会在 Python 3.11 和 3.12 上运行全部测试（[CI](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml)）。

## 基准测试

为了如实衡量效果，基准测试使用答案已知的色调：先把某个色调套用到一部分照片上，作为"参考照片"；每种方法根据这些参考照片生成一个 LUT；再把这个 LUT 用在你的其他照片上，和正确答案比较，使用 **ΔE 2000** 衡量差异。ΔE 2000 是衡量人眼可见色差的标准，低于约 1 时人眼就看不出差别。详情见 [bench/README.md](bench/README.md)（英文）。

使用作者的 45 张照片（两台索尼相机；城市、街头、人像、夜景、沙漠）和 8 个已知色调，每次测试用 15 张参考照片和 30 张输入照片（[完整表格](bench/RESULTS.md)）。数值为平均 ΔE 2000，越低越好：

| 方法 | 相同场景 | 不同场景 | 变差的照片（不同场景） |
|---|---|---|---|
| 不做任何改变 | 4.51 | 4.51 | – |
| Reinhard 色彩迁移 | 3.71 | 7.97 | 84% |
| 普通最优传输 | **0.62** | 7.41 | 77% |
| lookmatch | 0.99 | **3.88** | 41% |

在相同场景下，lookmatch 与正确答案的差距约在 1 ΔE 以内。在不同场景下，经典方法会让大多数照片比不做改变还差：它们把两组场景之间的差异误当成了色调（一组昏暗的峡谷照片会让它学到"把所有照片压暗"）。lookmatch 会先测量两组场景有多相似；当场景不同时，只学习在不同场景之间依然可靠的部分：黑白点，以及所有参考照片一致呈现的偏色。因此它是唯一平均胜过不做改变的方法，8 个色调中有 6 个更好。对于两个几乎不改变颜色的色调，它仍会多出约 2 ΔE 的变化（原来是 7）。目前它还无法从不同场景中学到中间调反差、饱和度和针对特定颜色的调整，所以参考照片和你的照片越相似，效果越好。原理见 [docs/method.md](docs/method.md#when-the-scenes-differ)（英文）。

## 许可证

MIT，见 [LICENSE](LICENSE)。
