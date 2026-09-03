# 贡献指南

感谢你对 PhotoLayout 的关注！我们欢迎任何形式的贡献：提交 Issue、改进文档、修复 Bug、增加新规格、实现路线图上的功能……

## 开始之前

- 大改动前请先开一个 Issue 讨论方案，避免方向不一致导致的返工。
- 提交 PR 前请确认相关测试全部通过。

## 开发环境搭建

要求 Python **3.11+**，在项目根目录执行：

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

## 运行测试

```bash
python -m unittest discover -s tests -v
```

新增或修改功能时，请同步补充不依赖 AI 模型的单元测试（参考 [tests/test_layout.py](tests/test_layout.py) 的写法）。

## 架构约定

请遵循现有的分层结构，保持模块职责清晰：

- **视觉算法**（人脸检测、裁剪、增强等）放入独立领域模块，如 `photolayout/portrait.py`
- **流程编排**统一由 `photolayout/service.py` 负责，算法模块之间不直接相互调用
- **入口层**（GUI、Web、批处理）直接调用服务层，不依赖 `photolayout/cli.py`
- **规格与配置**（照片尺寸、背景色、纸张参数）集中在 `photolayout/config.py`

## 提交规范

- 代码风格与项目现有代码保持一致（类型标注、docstring 使用中文简述用途）
- Commit message 简明描述改动意图，例如：`feat: 新增签证照规格`、`fix: 修复横版排版间距计算`
- 一个 PR 只做一件事，保持改动聚焦，便于审查

## 提交 Issue 的建议

- **Bug 反馈**：附上操作系统、Python 版本、完整报错信息，以及（如方便）可复现问题的示例照片特征描述
- **功能建议**：说明使用场景和期望效果，例如"希望支持日本签证 45×45mm 规格"

再次感谢你的贡献！🎉
