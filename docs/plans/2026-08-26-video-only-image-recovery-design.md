# Video-only 论文库清理与图片恢复设计

## 目标

- 只保留 `curation/video-2026-07-27-to-2026-08-26.txt` 中确认的 60 篇 Video 论文。
- 移除从 VLA 仓库继承的其余 1,852 篇论文记录、详情页、封面和论文图片缓存。
- 恢复论文真实图片功能，并让 60 篇论文尽可能全部拥有来源可追踪的图片。
- 重建并部署 GitHub Pages，验证线上数据、详情页和图片资源。

## 已确认事实

- 当前 `papers.md` 有 1,912 篇，其中本次 Video 清单为 60 篇。
- 当前图片 manifest 有 1,830 条，但本次 60 篇没有任何图片记录。
- `arxiv-autodrive-deepseek` 中已经验证两项图片修复：
  - 解析 arXiv HTML 相对图片路径时，不把论文 ID 重复拼接到 URL。
  - 图片质量评分只检查 URL path，不因合法域名 `arxiv.org` 含有 `arxiv` 而误判为坏图。
- 用修复后的 autodrive 代码对 60 篇进行只读探测，59 篇可以直接找到合格 HTML 图片；仅 `2608.24845` 需要兜底。
- 当前手动 `process-curated.yml` 只执行直接抓图，缺少 Node.js、Playwright、截图注册等兜底步骤，并受 `--max-items 30` 限制。

## 数据清理设计

- 新增确定性的清理脚本，以 curated ID 文件作为唯一保留集合。
- 默认执行只读预览；只有显式 `--apply` 才修改数据。
- 执行前必须验证：
  - curated ID 恰好 60 个且无重复；
  - 60 个 ID 全部存在于当前 `papers.md`；
  - 目标路径位于当前仓库内。
- 应用后：
  - `papers.md` 仅保留表头和 60 条完整记录，包括现有中文摘要；
  - 图片 manifest 仅保留这 60 个 ID 的有效记录；首次清理时这些记录为空；
  - 删除 `site/assets/paper-images` 下旧论文图片和缩略图；
  - `build_site.py` 继续负责重建并清空旧 `site/papers` 与 `site/covers`。
- 所有删除均通过正常 Git 提交保存，能从清理前提交恢复，不改写历史。

## 图片恢复链路

采用来源优先级明确的三层回退：

1. **arXiv HTML 真实图片**
   - 移植 autodrive 已验证的 URL 解析和评分修复。
   - 优先选择 figure 内、尺寸足够且不含 logo/icon/badge 等坏图提示的图片。
   - 成功后立即保存原图并更新 manifest。
2. **Playwright HTML 截图**
   - 对直接下载失败但 HTML/ar5iv 可渲染的论文，截取第一个满足尺寸要求的 figure/img。
   - 截图成功后立即注册到 manifest。
3. **PDF 兜底**
   - 下载官方 arXiv PDF。
   - 使用 PyMuPDF 检查前几页的嵌入式图片，过滤尺寸过小、极端长宽比和低像素资源，优先保存面积最大的主要图片。
   - 如果没有合格嵌入图，则渲染 PDF 首页作为论文封面。
   - manifest 明确记录 `source=pdf:image` 或 `source=pdf:first-page`。

不使用 AI 生成装饰图，避免把与论文无关的内容展示为论文原图。

## 工作流设计

- `process-curated.yml` 与正常部署工作流保持图片步骤一致：
  - 设置 Python 和 Node.js；
  - 安装 Python、npm 和 Chromium 依赖；
  - 直接抓取全部缺图论文，不再固定截断为前 30 篇；
  - 构建全部缺图论文的 Playwright 队列并注册成功截图；
  - 对仍缺图的论文执行 PDF 兜底；
  - 构建站点、提交生成文件并部署 Pages。
- 正常每日工作流也采用相同图片回退链路，未来新增论文可增量补图。
- 已有且文件有效的 manifest 条目自动跳过；失败论文不会阻塞其他论文。

## 测试与验收

- 单元测试覆盖：
  - curated 清理只保留精确 60 个 ID；
  - curated 缺失、重复或路径越界时拒绝应用；
  - 相对图片路径不会重复论文 ID；
  - `arxiv.org` 域名不会降低合法 figure 得分；
  - PDF 嵌入图选择与首页渲染兜底；
  - 两个 GitHub Actions 工作流都包含完整回退步骤且不再只处理前 30 篇。
- 本地实物验收：
  - `papers.md` 记录数为 60，链接唯一且全部属于 curated 清单；
  - 60 个详情页和 60 个封面页；
  - manifest 有 60 条且每条本地文件存在；
  - 随机抽查 HTML 图片和 PDF 兜底图片，确认不是 logo、空白页或错误页面。
- 远端验收：
  - GitHub Actions build/deploy 成功；
  - 线上 `data.json` 为 60 条；
  - 线上 manifest 为 60 条；
  - 首页、代表性详情页和代表性图片均返回 HTTP 200。

