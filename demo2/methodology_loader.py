"""
行业定义 Agent — 方法论文档加载器 (v5.2)

v5.2 升级：支持拆分模块加载 + 版本声明 + 版本一致性检查。

v4 的单文件 方法论-v2.md 调整时需要改代码（SLICE_MAP 关键词映射）。
v5 拆成 2-3 模块 + _meta.yaml 版本声明。保持正则切片逻辑作为 fallback。

v5.1 补充（评议 Q6）：
- 版本迁移简化策略：不支持运行时切换，手动替换全部文件
- _meta.yaml 与 fallback 版本一致性检查

v3.1 关键约束：拆分后需验证正则切片不丢章节
（模块间正则边界不一致会导致加载丢内容）。

兼容性：
- 无 _meta.yaml 时回退到 v4 单文件模式（load_methodology / load_slice 函数保留）
- v4 的 SLICE_MAP 关键词映射保留，作为模块加载的 fallback
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

# ============================================================
# Step ID → 方法论章节关键词映射（v4 保留，v5 作为模块匹配依据）
# ============================================================

SLICE_MAP: Dict[str, List[str]] = {
    "1_info_collection":       ["信息优先级", "参考框架", "Hard Rules"],
    "2_dimension_screening":   ["维度筛选原则", "Heuristics", "自检清单"],
    "3_structure_decision":    ["报告结构", "范围约束"],
    "4_content_generation":    ["Hard Rules", "推理展示", "范围约束"],
    "5_self_check":            ["自检清单"],
}


# ============================================================
# MethodologyLoader — v5 升级：拆分模块加载
# ============================================================

class MethodologyLoader:
    """v5 升级：支持拆分模块加载 + 版本声明。

    v5.1 补充（评议 Q6）：
    - 版本迁移简化策略：不支持运行时切换，手动替换全部文件
    - _meta.yaml 与 fallback 版本一致性检查

    v3.1 关键约束：拆分后需验证正则切片不丢章节
    （模块间正则边界不一致会导致加载丢内容）。
    """

    def __init__(self, methodology_dir: str = "方法论"):
        """初始化加载器。

        Args:
            methodology_dir: 方法论目录路径。默认相对于当前文件所在目录的"方法论"。
                             v5 新增：支持拆分模块目录。
                             v4 兼容：如果目录不存在，回退到单文件模式。
        """
        # 解析目录路径（相对于当前文件所在目录）
        p = Path(methodology_dir)
        if p.is_absolute():
            self.dir = p
        else:
            self.dir = (Path(__file__).parent / p).resolve()

        self._meta: Optional[dict] = None
        self._module_cache: dict[str, Optional[str]] = {}
        self._full_cache: Optional[str] = None
        # v4 兼容：单文件路径
        self._v4_single_file_path: Optional[Path] = None

    def _load_meta(self) -> dict:
        """加载 _meta.yaml。"""
        if self._meta is None:
            meta_path = self.dir / "_meta.yaml"
            if meta_path.exists():
                try:
                    import yaml
                    self._meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
                    # v5.1 补充（评议 Q6）：_meta.yaml 与 fallback 版本一致性检查
                    self._check_fallback_version_consistency()
                except ImportError:
                    print("[方法论加载器] 警告：pyyaml 未安装，回退到 v4 单文件模式")
                    self._meta = {"version": "v2", "fallback": "方法论-v2.md", "modules": []}
                except Exception as e:
                    print(f"[方法论加载器] _meta.yaml 解析失败: {e}，回退到 v4 单文件模式")
                    self._meta = {"version": "v2", "fallback": "方法论-v2.md", "modules": []}
            else:
                # 兼容 v4：无 _meta.yaml 时回退到单文件模式
                self._meta = {"version": "v2", "fallback": "方法论-v2.md", "modules": []}
        return self._meta

    def _check_fallback_version_consistency(self) -> None:
        """v5.1 新增（评议 Q6）：检查 fallback 文件版本与 _meta.yaml 是否一致。

        捕捉手动替换时"忘了更新 fallback 文件"的人为错误。
        """
        meta_version = self._meta.get("version", "")
        fallback_file = self._meta.get("fallback", "")
        fallback_path = self.dir / fallback_file
        if not fallback_path.exists():
            return
        fallback_content = fallback_path.read_text(encoding="utf-8")
        # 在 fallback 文件前 500 字符中查找版本声明（如 "v2", "v2.1"）
        # 这只是启发式检查，不强制要求 fallback 文件包含版本声明
        if meta_version and meta_version not in fallback_content[:500]:
            print(
                f"[警告] _meta.yaml 版本({meta_version})与 fallback 文件({fallback_file})不一致，"
                f"请检查手动替换时是否遗漏了 fallback 文件的更新"
            )

    def load_methodology(self) -> str:
        """加载完整方法论文档（fallback 文件）。

        Returns:
            方法论文档的完整 Markdown 文本。
        """
        if self._full_cache is None:
            meta = self._load_meta()
            fallback_file = meta.get("fallback", "方法论-v2.md")
            path = self.dir / fallback_file
            if not path.exists():
                # 兼容 v4：尝试从上级目录加载单文件
                v4_path = Path(__file__).parent / "方法论-v2.md"
                if v4_path.exists():
                    # v5.2 修复 P2 #1：fallback 不再静默，打印 warning 暴露配置错误（规则2：不确定就说不知道）
                    # 用 print 而非 warnings.warn，避免批量场景下被 warning filter 去重（与 line 111/156 风格一致）
                    print(
                        f"  [MethodologyLoader 警告] 指定目录 {self.dir} 下未找到 {fallback_file}，"
                        f"已回退到 v4 单文件模式 {v4_path}。请检查 methodology_dir 配置。"
                    )
                    # 可选严格模式：环境变量 METHODOLOGY_STRICT=true 时拒绝回退，硬失败
                    if os.getenv("METHODOLOGY_STRICT") == "true":
                        raise FileNotFoundError(
                            f"严格模式：指定目录 {self.dir} 下未找到 {fallback_file}，"
                            f"且 METHODOLOGY_STRICT=true，拒绝回退到 v4 单文件。"
                        )
                    path = v4_path
                    self._v4_single_file_path = v4_path
                else:
                    raise FileNotFoundError(
                        f"方法论文档不存在: {path}\n"
                        f"请确保 {fallback_file} 存在于 {self.dir} 目录下，"
                        f"或 方法论-v2.md 存在于上级目录。"
                    )
            self._full_cache = path.read_text(encoding="utf-8")
        return self._full_cache

    def load_slice(self, step_id: str) -> str:
        """按 step_id 返回相关的方法论章节。

        v5 新增：优先从拆分模块加载。
        v4 的 SLICE_MAP 关键词映射保留，作为模块匹配依据。
        v3.1 约束：拆分后需验证正则切片不丢章节。

        Args:
            step_id: 步骤标识，如 '1_info_collection'。

        Returns:
            对应步骤的方法论切片文本。
        """
        keywords = SLICE_MAP.get(step_id)
        if keywords is None:
            print(f"[方法论加载器] 警告：未知的 step_id '{step_id}'，回退到全量方法论。")
            return self.load_methodology()

        # v5 新增：优先从拆分模块加载
        meta = self._load_meta()
        modules = meta.get("modules", [])

        if modules:
            matched_modules: List[str] = []
            for module in modules:
                module_keywords = module.get("keywords", [])
                # 模块的关键词与 step 需要的关键词有交集则匹配
                if any(kw in keywords for kw in module_keywords):
                    module_content = self._load_module(module["file"])
                    if module_content:
                        matched_modules.append(module_content)

            if matched_modules:
                # 验证：合并后的内容应包含所有关键词
                merged = "\n\n---\n\n".join(matched_modules)
                self._verify_slice_completeness(step_id, keywords, merged)
                return merged

        # 回退到 v4 的正则切片逻辑
        return self._legacy_regex_slice(step_id, keywords)

    def _load_module(self, filename: str) -> Optional[str]:
        """加载单个模块文件（带缓存）。"""
        if filename not in self._module_cache:
            path = self.dir / filename
            if path.exists():
                self._module_cache[filename] = path.read_text(encoding="utf-8")
            else:
                self._module_cache[filename] = None
                print(f"[方法论加载器] 警告：模块文件不存在: {path}")
        return self._module_cache[filename]

    def _verify_slice_completeness(
        self, step_id: str, keywords: List[str], content: str
    ) -> None:
        """v3.1 约束：验证正则切片不丢章节。

        如果关键词在完整方法论中存在但在切片中缺失，打印警告。
        """
        try:
            full = self.load_methodology()
        except FileNotFoundError:
            return  # 完整方法论不存在时跳过验证

        for kw in keywords:
            if kw in full and kw not in content:
                print(f"[警告] Step {step_id} 的方法论切片丢失关键词: {kw}")

    def _legacy_regex_slice(self, step_id: str, keywords: List[str]) -> str:
        """v4 兼容：正则切片逻辑。"""
        full = self.load_methodology()
        if not keywords:
            return full

        # 匹配 ## 或 ### 级别标题的正则（捕获整行标题）
        heading_pattern = re.compile(r"^(#{2,3})\s+(.+)$", re.MULTILINE)
        sections: List[Dict[str, str]] = []
        matches = list(heading_pattern.finditer(full))

        for i, m in enumerate(matches):
            level = len(m.group(1))  # 2 或 3
            heading = m.group(2).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
            body = full[start:end].strip()
            sections.append({"heading": heading, "level": level, "body": body})

        # 子串匹配：章节标题中包含任一关键词即视为匹配
        matched: List[str] = []
        for sec in sections:
            heading = sec["heading"]
            if any(kw in heading for kw in keywords):
                # 在正文前加上标题行，保持可读性
                prefix = f"{'#' * max(sec['level'], 2)} {heading}"
                matched.append(f"{prefix}\n\n{sec['body']}")

        if not matched:
            print(
                f"[方法论加载器] 警告：step_id='{step_id}' 未匹配到任何章节 "
                f"(关键词: {keywords})，回退到全量方法论。"
            )
            return full

        result = "\n\n---\n\n".join(matched)

        # 空切片降级：总长度不足 100 字符视为无效
        if len(result.strip()) < 100:
            print(
                f"[方法论加载器] 警告：step_id='{step_id}' 匹配内容过短 "
                f"({len(result.strip())} 字符)，回退到全量方法论。"
            )
            return full

        return result


# ============================================================
# v4 兼容：模块级函数（保持 load_methodology / load_slice 可直接调用）
# ============================================================

_default_loader: Optional[MethodologyLoader] = None


def _get_default_loader() -> MethodologyLoader:
    global _default_loader
    if _default_loader is None:
        _default_loader = MethodologyLoader()
    return _default_loader


def load_methodology(path: str = "方法论-v2.md") -> str:
    """v4 兼容：加载方法论文档全文。

    v5 注意：此函数委托给 MethodologyLoader.load_methodology()。
    path 参数在 v5 中被忽略（由 _meta.yaml 的 fallback 字段决定），
    保留仅为向后兼容。
    """
    return _get_default_loader().load_methodology()


def load_slice(step_id: str, path: str = "方法论-v2.md") -> str:
    """v4 兼容：按 step_id 返回对应的方法论切片。

    v5 注意：此函数委托给 MethodologyLoader.load_slice()。
    path 参数在 v5 中被忽略，保留仅为向后兼容。
    """
    return _get_default_loader().load_slice(step_id)
