# VLM集成修复与Km/Vmax提取率提升

## 更新时间
2026-04-28 01:05

## 更新类型
- Bug 修复 / 功能开发

## 背景
VLM（视觉语言模型）集成存在多个关键问题，导致：
1. 图片路径无法正确解析，vlm_tasks始终为0
2. `_call_vlm` 和 `_merge_vlm` 方法被错误放在 `RuleExtractor` 类中
3. `_merge_vlm` 的数据格式与VLM实际返回格式不匹配
4. Km/Vmax提取率极低（20%/0%）

## 改动内容

### 1. 图片路径解析修复（batch_test_2021.py）
- **问题**：预处理器使用临时目录，但图片文件在原始解析输出目录中，导致"文件不存在"跳过所有图片
- **修复**：传入 `images_root=str(parsed_path.parent)` 参数，让预处理器能正确找到图片文件
- **代码**：`NanozymePreprocessor(json_path=..., output_root=..., images_root=str(parsed_path.parent), ...)`

### 2. 图片持久化保存（batch_test_2021.py）
- **问题**：临时目录在预处理后被删除，但vlm_tasks中的image_path指向临时目录中的图片
- **修复**：在删除临时目录前，将图片复制到预处理输出目录的 `{stem}_images/` 子目录，并更新vlm_tasks中的路径
- **代码**：
  ```python
  img_output_dir = PREPROC_DIR / f"{stem}_images"
  for task in mid_task.get("vlm_tasks", []):
      old_path = task.get("image_path", "")
      if old_path and Path(old_path).exists():
          img_output_dir.mkdir(parents=True, exist_ok=True)
          new_path = img_output_dir / Path(old_path).name
          shutil.copy2(old_path, str(new_path))
          task["image_path"] = str(new_path.resolve())
  ```

### 3. VLM方法类归属修复（single_main_nanozyme_extractor.py）
- **问题**：`_call_vlm` 和 `_merge_vlm` 被错误放在 `RuleExtractor` 类中，但它们引用 `self.client` 和 `self.config`，这些是 `SingleMainNanozymePipeline` 的属性
- **修复**：将这两个方法从 `RuleExtractor` 类移到 `SingleMainNanozymePipeline` 类中
- **影响**：修复了 `AttributeError: 'SingleMainNanozymePipeline' object has no attribute '_call_vlm'`

### 4. VLM合并逻辑重写（single_main_nanozyme_extractor.py）
- **问题**：`_merge_vlm` 期望VLM返回顶层字段如 `particle_size`, `kinetics_values`，但VLM实际返回 `extracted_values` 嵌套结构
- **VLM实际返回格式**：
  ```json
  {
    "figure_type": "mechanism_diagram",
    "extracted_values": {
      "Km": [{"value": 1.79, "unit": "mM", "material": null}],
      "Vmax": [{"value": null, "unit": null, "material": null}],
      "particle_size": {"value": null, "unit": "nm"},
      "sensing_performance": {"LOD": null, "linear_range": null},
      "other_values": []
    },
    "observations": [],
    "reliability_note": null
  }
  ```
- **修复**：重写 `_merge_vlm` 从 `extracted_values` 中提取Km/Vmax/particle_size/sensing_performance/other_values
- **关键改进**：VLM提取的Km/Vmax值现在会自动合并到 `main_activity.kinetics` 中（当规则提取未找到时）

## 未改动内容
- `nanozyme_preprocessor_midjson.py`：未修改（images_root参数已存在）
- `vlm_extractor.py`：未修改
- `extraction_pipeline.py`：未修改
- `config.yaml`：未修改
- `test_single_main_nanozyme.py`：未修改（32个现有测试全部通过）

## 验证方式
- 32个单元测试全部通过（pytest）
- LLM模式批量测试：5/5 PASS
- LLM+VLM模式批量测试：3/3 PASS
- Km提取率：从 20%（1/5, LLM only）提升到 67%（2/3, LLM+VLM）
  - 2021_06a8d32c (Pd): Km=1.79 ✅（VLM从图片中提取）
  - 2021_36e77786 (Cu-HCF SSNEs): Km=105.0 ✅（VLM从图片中提取）
  - 2021_73e66402 (Mn/PSAE): Km=None（该论文无动力学数据）

## 风险与后续
- **VLM提取的Km值需人工审核**：如Km=105.0可能单位有误，需确认是否为mM
- **Vmax提取率仍为0%**：VLM可能无法从图片中准确读取Vmax值，需优化VLM prompt
- **VLM API延迟**：每张图片约20-30秒，5张图片约2分钟，批量处理时需考虑超时
- **图片文件管理**：预处理输出目录中会保留图片副本，需定期清理
