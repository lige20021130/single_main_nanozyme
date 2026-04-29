# 拔尖系统深度优化：多维度数据提取增强

## 更新时间
2026-04-28 16:30

## 更新类型
- 功能开发 / 架构调整

## 背景
原系统在纳米酶关键数据维度的提取能力有限，动力学参数仅支持Km/Vmax，缺少kcat/kcat_Km；合成路径无结构化提取；pH/温度仅有单一值提取；尺寸/物理特性提取极简。需要深度优化以显著提高数据提取准确率。

## 改动内容

### 1. Schema扩展 (single_main_nanozyme_extractor.py)
- Schema版本从v1升级到v2
- `selected_nanozyme`新增字段：`size_unit`, `size_distribution`, `crystal_structure`, `surface_area`, `zeta_potential`, `pore_size`
- `selected_nanozyme`新增嵌套结构：`synthesis_conditions`（含temperature, time, precursors, method_detail）
- `main_activity`新增嵌套结构：`pH_profile`（含optimal_pH, pH_range, pH_stability_range）
- `main_activity`新增嵌套结构：`temperature_profile`（含optimal_temperature, temperature_range, thermal_stability）
- `main_activity.kinetics`新增字段：`kcat`, `kcat_unit`, `kcat_Km`, `kcat_Km_unit`
- 新增schema验证键集合：`_PH_PROFILE_KEYS`, `_TEMP_PROFILE_KEYS`, `_SYNTHESIS_COND_KEYS`
- `validate_schema`函数增加对新嵌套字段的自动补全

### 2. 动力学参数提取增强 (single_main_nanozyme_extractor.py)
- `_KM_PATTERNS`从5个扩展到9个：新增"Km of X was"、"Km(X) = X × 10^-N"、"Michaelis constant"等模式
- `_VMAX_PATTERNS`从9个扩展到11个：新增"Vmax of X was"、"maximum velocity"等模式
- 新增`_KCAT_PATTERNS`（4个模式）：支持kcat(TMB)、kcat for TMB、turnover number/frequency
- 新增`_KCAT_KM_PATTERNS`（4个模式）：支持kcat/Km、specificity constant、catalytic efficiency
- 所有动力学模式增加±误差格式支持和科学计数法增强

### 3. 合成路径与制备方法提取 (single_main_nanozyme_extractor.py)
- 新增`_SYNTHESIS_METHODS`（25种合成方法）：hydrothermal, solvothermal, co-precipitation, sol-gel, calcination, CVD, electrospinning, microwave, template-assisted, self-assembly, biomimetic mineralization, green synthesis等
- 新增`_SYNTHESIS_CONDITION_PATTERNS`：提取合成温度、时间、前驱体

### 4. pH特性提取增强 (single_main_nanozyme_extractor.py)
- 新增`_PH_PATTERNS`字典（3类共9个模式）：
  - optimal_pH：optimal pH was、pH optimum、maximum activity at pH等
  - pH_range：pH range of X-Y、active pH range
  - pH_stability：pH stability range、stable over pH、retained activity over pH

### 5. 温度特性提取增强 (single_main_nanozyme_extractor.py)
- 新增`_TEMPERATURE_PATTERNS`字典（3类共11个模式）：
  - optimal_temperature：optimal temperature was、T opt、maximum activity at X °C等
  - temperature_range：temperature range of X-Y °C
  - thermal_stability：thermal stability up to、TGA showed decomposition at等

### 6. 尺寸与物理特性提取增强 (single_main_nanozyme_extractor.py)
- 新增`_SIZE_PATTERNS`（8个模式）：particle size、diameter、size distribution、DLS、hydrodynamic size
- 新增`_SURFACE_AREA_PATTERNS`（3个模式）：BET surface area
- 新增`_ZETA_POTENTIAL_PATTERNS`（2个模式）：zeta potential、surface charge
- 新增`_PORE_SIZE_PATTERNS`（3个模式）：pore size/diameter、BJH pore size
- 新增`_CRYSTAL_STRUCTURE_PATTERNS`（9个模式）：spinel, perovskite, cubic, amorphous, XRD confirmed等

### 7. RuleExtractor新增方法 (single_main_nanozyme_extractor.py)
- `_extract_kcat_from_text`：从文本提取kcat和kcat/Km
- `_extract_pH_profile`：提取optimal_pH、pH_range、pH_stability_range
- `_extract_temperature_profile`：提取optimal_temperature、temperature_range、thermal_stability
- `_extract_synthesis_method`：提取合成方法和合成条件
- `_extract_size_properties`：提取尺寸和晶体结构
- `_extract_physical_properties`：提取比表面积、Zeta电位、孔径

### 8. LLM System Prompt增强 (single_main_nanozyme_extractor.py)
- 新增KINETICS RULES详细指引：kcat/kcat/Km格式示例
- 新增SYNTHESIS METHOD RULES：25种合成方法名称、合成条件格式
- 新增pH PROFILE RULES：optimal_pH、pH_range、pH_stability_range提取指引
- 新增TEMPERATURE PROFILE RULES：optimal_temperature、temperature_range、thermal_stability提取指引
- 新增SIZE AND PHYSICAL PROPERTIES RULES：size、crystal_structure、surface_area等提取指引
- 更新OUTPUT STRUCTURE以包含所有新字段

### 9. 酶类型扩展 (nanozyme_models.py, activity_selector.py)
- 新增5种酶类型：NITROREDUCTASE, HYDROLASE, PHOSPHATASE, LACCASE, HALOPEROXIDASE
- ENZYME_REGISTRY新增对应关键词、底物和检测方法
- ENZYME_TYPE_NORMALIZATION新增OXD-like、ALP-like、NTR-like等缩写映射

### 10. NumericValidator增强 (numeric_validator.py)
- 新增KCAT_UNITS和KCAT_KM_UNITS单位集合
- 新增_KCAT_MAGNITUDE_RANGE和_KCAT_KM_MAGNITUDE_RANGE范围校验
- validate_kinetics_entry增加kcat和kcat_Km参数验证
- resolve_kinetics增加kcat和kcat_Km候选排序和解析

### 11. SingleRecordAssembler更新 (single_record_assembler.py)
- `_build_selected_nanozyme`新增synthesis_method、synthesis_conditions、crystal_structure、surface_area、zeta_potential、pore_size、size_unit、size_distribution字段
- `_build_main_activity_dict`新增conditions、pH_profile、temperature_profile、kcat、kcat_Km、mechanism字段
- 移除旧的pH_opt和T_opt字段，替换为结构化的pH_profile和temperature_profile

### 12. DiagnosticsBuilder更新 (diagnostics_builder.py)
- WARNING_ENUMS新增：no_pH_profile, no_temperature_profile, no_synthesis_method, no_size_info

### 13. 测试更新 (test_single_main_nanozyme.py)
- 更新test_schema_structure以匹配新的kinetics字段集合

## 未改动内容
- extraction_pipeline.py：主流程未改动
- llm_extractor.py：LLM调用逻辑未改动
- application_extractor.py：应用提取逻辑未改动
- table_classifier.py：表格分类逻辑未改动
- figure_handler.py：图片处理逻辑未改动

## 验证方式
- 运行 `python -m pytest test_single_main_nanozyme.py -v`
- 32个测试全部通过
- 新增的schema字段在validate_schema中自动补全测试通过

## 风险与后续
- 新增的规则提取方法需要通过实际文献数据验证提取准确率
- LLM prompt大幅扩展，可能影响token消耗和响应时间
- 部分正则模式可能存在误匹配风险，需要在更多文献上测试
- 建议下一步：构建高质量标注数据集，对新增提取维度进行准确率评估
- 建议下一步：对pH/温度/尺寸等维度的提取进行端到端测试
