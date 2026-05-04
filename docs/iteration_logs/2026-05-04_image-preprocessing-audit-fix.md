# 图片预处理丢失审查与修复

## 更新时间
2026-05-04 10:15

## 更新类型
- Bug 修复 / 功能优化

## 背景
对2021.6.1文件夹中105篇纳米酶文献PDF进行图片预处理审查，发现系统解析和预处理存在图片丢失问题。总体存活率仅48.6%，9篇文献100%图片丢失，44张≥100×100尺寸的图片因无caption被误过滤。

## 改动内容

### 1. 修复 WinError 206 路径过长导致预处理崩溃
- **文件**: `nanozyme_preprocessor_midjson.py:333-338`
- **问题**: 当PDF文件名过长时，`high_value_dir`路径超过Windows 260字符限制，导致`mkdir`失败
- **修复**: `pdf_stem`超过80字符时自动截断为`年份_MD5哈希前8位`格式
- **影响**: 修复了3篇100%丢失文献中的2篇（从崩溃变为正常处理）

### 2. 降低 uncaptioned_min_both 阈值
- **文件**: `nanozyme_preprocessor_midjson.py:159`
- **改动**: `uncaptioned_min_both` 从 200 降至 150
- **效果**: 尺寸在150-200之间的无caption图片不再被强制过滤，预计可多保留约20+张中等尺寸科学图表

### 3. 增强 caption 检测支持 Table 格式
- **文件**: `nanozyme_preprocessor_midjson.py:176-178, 4403, 4424-4427, 4446`
- **改动**:
  - `caption_patterns` 配置新增 `"table"` 类别，匹配 `^table\s+(\d+)\b`
  - `_parse_caption_label` 遍历顺序加入 `"table"`
  - fallback正则匹配加入 `^table\.?\s*(\d+)\b`
  - `_find_fallback_caption` 中 `table` → `Table` 映射
- **效果**: Table 1/Table 2等表格标题被识别为caption，关联的图片不再被当作"无caption小图"过滤

## 未改动内容
- `opendataloader_pdf` 解析器本身未改动（6篇解析完全失败的文献需要从解析器层面解决）
- `max_images_main`/`max_images_supplementary` 截断限制未调整（本次测试中未触发）
- VLM阶段的二次过滤逻辑未改动

## 验证方式
- 对105篇文献运行回归测试，99篇预处理成功，0篇报错
- 之前3篇预处理崩溃的文献现在全部正常处理
- 总存活图片565张，平均caption匹配率0.746
- 丢弃原因分布：无caption小图593、尺寸过小247、文件不存在37、文件过小23

## 风险与后续
- 降低阈值可能让少量非科学图片（如期刊装饰图）进入vlm_tasks，但影响有限
- 6篇解析完全失败的文献（parse_no_output）需要排查opendataloader_pdf兼容性问题
- 3篇"文件不存在"的文献（解析器未提取图片文件）需要在解析阶段增加fallback机制
- git push因网络问题暂未成功，commit已保存在本地
