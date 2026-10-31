<p align="center">
  <a href="README.md">English</a> · <b>简体中文</b>
</p>

# lookmatch

[![CI](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml/badge.svg)](https://github.com/ShadowSkeleton/lookmatch/actions/workflows/ci.yml)

给 lookmatch 一张或几张你喜欢的调色照片，再加上一个装着你自己照片的文件夹。它会测量两边的颜色，生成一个 LUT，让你这台相机拍的照片都能呈现同样的色调，包括你以后拍的照片。你会得到可以在 Lightroom、Photoshop、DaVinci Resolve 等软件里使用的 LUT 和预设。

> **当前状态：** 早期开发中，还不能正式使用。整套引擎已经完成并通过测试，lookmatch 生成的 LUT 在 Photoshop 和 DaVinci Resolve 里的效果完全一致。当参考照片和你的照片拍的是相似的场景时，色调匹配效果很好；当两边场景差别很大时，目前还不行，详见[基准测试](#基准测试)。欢迎 Star 关注进展。

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

**从照片中学习色调。** 左：你的照片（相机直出的 JPEG）。中：目标，一个已知的青橙色调。右：lookmatch 用默认设置从参考照片中学到的色调，套用在你的照片上。

<img alt="马蹄湾的三个版本。左为原图；中为青橙色调，云层呈暖暖的桃色；右为 lookmatch 的结果，和中间几乎一样，只是云层的橙色稍淡一些。" src="docs/figures/photo_match.jpg" width="100%">

目标色调与原图相差 ΔE 6.15；lookmatch 的结果与目标只差 ΔE 1.30，即使并排对比也很难看出差别（三张示例照片在 1.30 到 2.35 之间）。这是**简单情况**：参考照片就是这几个相同场景套用色调后的结果。当参考照片拍的是不同场景时，lookmatch 目前还不行（见[基准测试](#基准测试)）。

**用在测试色卡上。** 灰阶、24 色 ColorChecker 色卡和纯原色，左为原图，右为套用后。

<img alt="测试色卡套用测试色调前后对比。" src="docs/figures/chart_before_after.png" width="100%">

**在你的软件里效果一样。** 把同一个 LUT 在 Photoshop 和 DaVinci Resolve 中套用到测试色卡上，测量全部 69 个色块：Photoshop 与 lookmatch 完全一致，Resolve 的差异在 1/255 以内（[结果](bench/APP_CHECK_RESULTS.md)）。

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

首次结果，仅用 4 张照片和 8 个已知色调（[完整表格](bench/RESULTS.md)）。数值为平均 ΔE 2000，越低越好：

| 方法 | 相同场景 | 不同场景 |
|---|---|---|
| 不做任何改变 | 4.67 | **4.67** |
| Reinhard 色彩迁移 | 2.91 | 13.60 |
| 普通最优传输 | **0.42** | 15.13 |
| lookmatch | 1.26 | 14.23 |

当参考照片和你的照片拍的是相同场景时，色调匹配效果很好。当两边场景不同时，所有方法（包括 lookmatch）都会让照片变得比不做改变还差：它们把场景之间的差异误当成了色调。这是目前最主要的未解决问题，基准测试就是为了衡量每一次解决它的尝试。只有 4 张照片，这些数字只是初步信号，还不能作为结论。

## 许可证

MIT，见 [LICENSE](LICENSE)。
