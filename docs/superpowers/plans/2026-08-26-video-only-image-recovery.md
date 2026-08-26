# Video-only 数据清理与论文图片恢复实施计划

> **执行方式：** 在当前任务中逐项实施；每个功能先写失败测试，再做最小修改使测试通过。

**目标：** 将仓库收敛为策展清单中的 60 篇 Video 论文，清除继承的 VLA/自动驾驶旧数据，并让每篇论文都获得可部署、可验证的本地图片。

**总体方案：** 增加一个带 dry-run 的精确清理脚本；修复 HTML 图片抓取的 URL 解析和候选评分；保留 Playwright DOM 截图作为第二层兜底；增加 PyMuPDF 的 PDF 图片/首页渲染作为第三层兜底。两条 GitHub Actions 工作流使用同一条完整链路，最后重建静态站点并验证 GitHub Pages。

**技术栈：** Python 3.11、pytest、requests、Pillow、PyMuPDF、Node.js 20、Playwright Chromium、GitHub Actions、GitHub Pages。

---

## Task 1：实现可审计的 Video-only 清理器

**文件：**

- 新建：`scripts/prune_to_curated_video.py`
- 新建：`tests/test_prune_to_curated_video.py`

### 1.1 先写清理行为测试

测试覆盖以下不变量：

- 默认 dry-run 不修改任何文件。
- `--apply` 后 `papers.md` 只保留清单中的论文，并保持原有表格行内容与顺序。
- 清单中缺少于 `papers.md` 的 ID 时必须失败，不能产生部分清理。
- 重复 ID 必须失败。
- 只重置 `site/assets/paper-images/` 和 `site/assets/paper-images.json`，不碰 `site/CNAME` 等无关文件。
- 删除目标必须解析到仓库根目录内部的精确路径。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prune_to_curated_video.py -q
```

预期：测试因脚本尚不存在而失败。

### 1.2 实现清理器

脚本提供以下接口：

```python
def load_curated_ids(path: Path, expected_count: int | None = 60) -> list[str]: ...
def parse_paper_rows(markdown: str) -> tuple[list[str], list[PaperRow]]: ...
def build_pruned_markdown(markdown: str, keep_ids: list[str]) -> str: ...
def prune_repository(
    root: Path,
    curated_file: Path,
    *,
    expected_count: int = 60,
    apply: bool = False,
) -> CleanupReport: ...
```

命令行默认只输出计划；只有显式 `--apply` 才执行：

```powershell
.\.venv\Scripts\python.exe scripts/prune_to_curated_video.py \
  --curated-file curation/video-2026-07-27-to-2026-08-26.txt

.\.venv\Scripts\python.exe scripts/prune_to_curated_video.py \
  --curated-file curation/video-2026-07-27-to-2026-08-26.txt \
  --apply
```

实现要求：

- 写文件前先完成全部输入验证。
- 对图片目录使用 `Path.resolve()` 和 `is_relative_to(root.resolve())` 校验。
- 只允许删除精确路径 `site/assets/paper-images`。
- 图片清单重置为 `{}`。
- 报告保留数、删除数、图片文件数以及实际是否修改。

### 1.3 运行测试并提交

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prune_to_curated_video.py -q
git add scripts/prune_to_curated_video.py tests/test_prune_to_curated_video.py
git commit -m "feat: add audited video-only cleanup"
```

---

## Task 2：修复 HTML 图片抓取的两个根因

**文件：**

- 修改：`scripts/fetch_paper_images.py`
- 新建：`tests/test_fetch_paper_images.py`

### 2.1 为 URL 解析和评分写回归测试

测试构造一段最小 arXiv HTML：

```html
<figure class="ltx_figure">
  <img src="2608.23011v1/motivation_v2.png" alt="Method overview">
</figure>
```

断言：

- 基址 `https://arxiv.org/html/2608.23011v1` 解析后的图片 URL 是
  `https://arxiv.org/html/2608.23011v1/motivation_v2.png`，不能重复论文 ID。
- `arxiv.org` 域名本身不触发 `BAD_HINTS` 中的 `arxiv` 惩罚。
- 真正位于路径、alt 或 class 中的 logo/icon/arxiv 提示仍会被惩罚。
- 合格 figure 图片的得分高于 logo 和页眉素材。

运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fetch_paper_images.py -q
```

预期：现有实现至少在基址和评分两项失败。

### 2.2 做最小修复

修改两处：

```python
parser = ArxivImageParser(base_url=final_html_url)
```

以及：

```python
hint_text = " ".join(
    [urlparse(candidate.url).path, candidate.alt, candidate.classes]
).lower()
```

同时把 User-Agent 中旧项目名改为 `daily-arxiv-video`，便于服务端日志识别。

### 2.3 本地测试与真实只读探测

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fetch_paper_images.py -q
```

用修复后的选择逻辑对 60 篇论文做不落盘探测，记录 direct HTML 成功数和需要兜底的 ID。当前基线预期为 59/60，唯一 PDF 兜底候选为 `2608.24845`；若实时 arXiv 页面变化，以探测结果为准。

### 2.4 提交

```powershell
git add scripts/fetch_paper_images.py tests/test_fetch_paper_images.py
git commit -m "fix: recover arxiv html paper images"
```

---

## Task 3：增加 PDF 图片与首页渲染兜底

**文件：**

- 修改：`requirements.txt`
- 新建：`scripts/fetch_pdf_fallback_images.py`
- 新建：`tests/test_fetch_pdf_fallback_images.py`

### 3.1 先写合成 PDF 测试

使用 PyMuPDF 在临时目录生成两份小 PDF：

1. 第一份嵌入一张 800×400 图片，断言脚本提取该图片并登记 `source=pdf:image`。
2. 第二份只有矢量文字，断言脚本渲染第一页并登记 `source=pdf:first-page`。

共同断言：

- 产物位于 `site/assets/paper-images/`。
- manifest 路径是相对站点根的 POSIX 路径。
- 图片可被 Pillow 打开，宽高有效。
- 已有 manifest 条目默认跳过，不重复下载。

### 3.2 增加依赖并实现脚本

在 `requirements.txt` 增加：

```text
PyMuPDF>=1.24,<2
```

脚本处理所有 manifest 缺失的论文：

```text
papers.md
   -> https://arxiv.org/pdf/<id>
   -> 前 3 页嵌入图片筛选
   -> 找不到合格位图时渲染第 1 页
   -> 本地 PNG
   -> site/assets/paper-images.json
```

图片筛选约束：

- 最小宽 320、高 160、面积 100000 像素。
- 宽高比在 0.2 到 5 之间。
- 优先面积最大的合格图片。
- PyMuPDF pixmap 统一转换为 RGB PNG，避免 CMYK/JBIG 等浏览器兼容问题。
- 每成功一篇就原子保存 manifest，防止中途失败丢失进度。
- `--max-items 0` 表示不限量；默认只处理缺失项。

### 3.3 测试并提交

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest tests/test_fetch_pdf_fallback_images.py -q
git add requirements.txt scripts/fetch_pdf_fallback_images.py tests/test_fetch_pdf_fallback_images.py
git commit -m "feat: add pdf fallback for paper images"
```

---

## Task 4：让手动与定时工作流使用同一图片链路

**文件：**

- 修改：`.github/workflows/process-curated.yml`
- 修改：`.github/workflows/deploy.yml`
- 新建：`tests/test_workflows.py`

### 4.1 先写工作流契约测试

对两个 YAML 文件断言均包含且顺序一致：

1. Python 依赖安装。
2. Node.js 20 设置。
3. Playwright Chromium 安装。
4. HTML 直接抓取，`--max-items 0`。
5. fallback queue 构建，`--max-items 0`。
6. Playwright 渲染。
7. fallback 注册。
8. PDF 兜底，`--max-items 0`。
9. 静态站点构建。

并断言工作流的 `permissions` 允许提交生成内容。

### 4.2 修改两条工作流

手动 `process-curated.yml` 补齐 Node/Playwright 与两级兜底；定时 `deploy.yml` 去掉 30/20 的截断。图片处理链统一为：

```yaml
- name: Fetch paper images from arXiv HTML
  run: python scripts/fetch_paper_images.py --max-items 0

- name: Build browser fallback queue
  run: python scripts/build_paper_image_fallback_queue.py --max-items 0

- name: Render browser fallback images
  run: node scripts/render_paper_image_fallbacks.mjs

- name: Register browser fallback images
  run: python scripts/register_paper_image_fallbacks.py

- name: Fetch PDF fallback images
  run: python scripts/fetch_pdf_fallback_images.py --max-items 0
```

### 4.3 测试并提交

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_workflows.py -q
git add .github/workflows/process-curated.yml .github/workflows/deploy.yml tests/test_workflows.py
git commit -m "ci: complete paper image fallback pipeline"
```

---

## Task 5：执行精确清理并真实回填 60 篇图片

**文件：**

- 修改：`papers.md`
- 重建：`site/assets/paper-images.json`
- 重建：`site/assets/paper-images/`
- 重建：`site/index.html`
- 重建：`site/papers/`
- 重建：`site/covers/`
- 可能修改：由 `scripts/build_site.py` 生成的其他站点文件

### 5.1 先 dry-run 并核对边界

```powershell
.\.venv\Scripts\python.exe scripts/prune_to_curated_video.py \
  --curated-file curation/video-2026-07-27-to-2026-08-26.txt
```

必须满足：

- 保留 60 篇。
- 删除 1852 篇继承记录；若输入已变化，以实际差值为准并暂停核对异常。
- 删除目标只有旧图片目录和 manifest。
- 不修改摘要正文、清单、脚本之外的用户文件。

### 5.2 执行授权范围内的清理

```powershell
.\.venv\Scripts\python.exe scripts/prune_to_curated_video.py \
  --curated-file curation/video-2026-07-27-to-2026-08-26.txt \
  --apply
```

清理可通过 Git 历史恢复；执行后立即核对 60 个 ID 与策展清单完全一致。

### 5.3 回填图片

```powershell
.\.venv\Scripts\python.exe scripts/fetch_paper_images.py --max-items 0 --workers 8
.\.venv\Scripts\python.exe scripts/build_paper_image_fallback_queue.py --max-items 0
node scripts/render_paper_image_fallbacks.mjs
.\.venv\Scripts\python.exe scripts/register_paper_image_fallbacks.py
.\.venv\Scripts\python.exe scripts/fetch_pdf_fallback_images.py --max-items 0
```

验收：manifest 必须覆盖 60/60。若 HTML 或 Playwright 因 arXiv 短时失败，PDF 兜底继续补齐；若仍缺失，记录具体 ID 和原始错误，不用占位图冒充论文图。

### 5.4 重建站点并做本地验收

```powershell
.\.venv\Scripts\python.exe scripts/build_site.py
.\.venv\Scripts\python.exe -m pytest -q
```

核对：

- `papers.md` 恰好 60 行论文记录。
- manifest 恰好覆盖这 60 个 ID。
- 站点首页恰好 60 张论文卡片。
- 每个图片文件和缩略图存在且可打开。
- 随机查看至少 3 张图片，其中必须包括 PDF 兜底论文。
- 旧论文详情目录和旧封面目录已由构建器移除。

### 5.5 提交生成结果

```powershell
git add papers.md site/assets/paper-images.json
git add -u site
git add -f site
git commit -m "data: publish video-only paper collection [skip ci]"
```

---

## Task 6：推送、部署和线上验证

### 6.1 推送全部本地提交

```powershell
git push origin master
```

### 6.2 触发手动完整流程

```powershell
gh workflow run process-curated.yml --repo MHQQysh/daily-arxiv-video --ref master
gh run watch --repo MHQQysh/daily-arxiv-video --exit-status
```

若工作流生成新提交，则拉取并确认本地/远端一致。

### 6.3 验证 GitHub 和 Pages

至少检查：

- GitHub `master` 的最新提交等于本地 HEAD。
- 工作流结论为 `success`，不是 `cancelled`。
- Pages 首页返回 HTTP 200，只显示 60 篇 Video 论文。
- `site/assets/paper-images.json` 在线可读且包含 60 项。
- 至少 3 个真实图片 URL 和缩略图 URL 返回 HTTP 200。
- 一个已知旧 VLA 论文详情路径不再存在。

最终向用户报告：保留/删除记录数、三层图片来源分布、测试结果、工作流 run 链接、线上站点链接，以及任何仍受 arXiv 实时状态影响的边界。
