# 证件照美颜与合规增强设计

日期：2026-09-06

## 背景与目标

PhotoLayout 目前的 `enhance_portrait`（`portrait.py`）只做基础画质增强（人脸区域降噪、低光自然提亮、轻度锐化），路线图中"正装换衣、美颜优化"尚未实现。本设计新增一套证件照专用的美颜处理，目标是让成片"靓丽"的同时不违背证件照行业的核心要求——**真实反映本人近期相貌**（不改变五官比例、不抹除永久性身份特征如痣/疤痕、光照均匀、肤色自然）。

## 调研结论（用于指导范围取舍）

- 证件照/护照照片规范的共性要求：真实性、光照均匀、纯色背景、构图比例、表情中性五官可辨。
- 主流证件照 App 的常见修图手法：磨皮（双边滤波/高低频分离）、美白（LAB 空间 L 通道提升 + b 通道降低）、局部瑕疵柔化（基于关键点划定眼下/两颊区域做色彩校正，而非全局滤镜）、牙齿美白（嘴部关键点抠图 + HSV 调整）、瘦脸/大眼（基于关键点的局部图像形变）。
- **明确排除**：基于 inpainting 的痘印/痣斑"抹除式"修复。算法难以可靠区分"临时瑕疵"与"永久性身份特征"，误删会直接导致合规风险，因此本设计只做色彩层面的柔化，不做结构性抹除。

## 范围

新增效果（用户已确认）：
1. 自然磨皮 + 肤色美白（肤色区域，非全局）
2. 临时性瑕疵柔化：黑眼圈提亮、两颊/鼻翼泛红降低（色彩校正，非抹除）
3. 五官微调（默认关闭，需用户主动开启）：瘦脸、大眼、牙齿美白

不在本次范围内：痘印/痣斑抹除式修复、整体换脸类效果、深度学习人脸解析分割（方案 B，见下）。

## 技术方案

**采用方案 A：基于现有依赖的传统 CV 算法路线。** 不引入新依赖（不用 dlib、不用人脸解析分割模型如 BiSeNet），复用项目已有的 MediaPipe `face_landmarker.task`（468 点全脸网格模型，已在用于双眼扶正）。

被否决的方案：
- **方案 B（人脸解析分割模型）**：精度更高，但需引入 PyTorch + 预训练权重，体量远超现有 14MB 模型规模，违背项目"轻量本地运行"定位，不采用。
- **方案 C（分阶段交付，先肤色类后五官类）**：会拆成两次设计/实施，本次一并设计、实现可分阶段验证。

## 新增/修改模块

### `detection.py`（修改）

新增一个函数，复用现有 `face_landmarker.task` 模型：

```python
def detect_face_mesh(rgb: np.ndarray) -> list[Point] | None:
    """返回 468 点全脸网格像素坐标；未检测到人脸或降级时返回 None。"""
```

与 `detect_eye_line` 各自独立调用（作用于流水线不同阶段的不同图像，无法共享一次推理结果），实现上复用 `_open_detector` 等既有辅助函数。

### `beauty.py`（新增，领域模块，与 `portrait.py` 平级）

```python
def build_skin_mask(landmarks, shape) -> np.ndarray:
    """人脸轮廓减去眼/眉/唇/鼻孔区域，得到纯肤色区域的浮点权重蒙版。"""

def smooth_and_whiten_skin(image, mask, intensity: float) -> Image.Image:
    """双边滤波磨皮 + LAB 空间 L 提升/b 降低美白，按蒙版强度混合。"""

def reduce_blemishes(image, landmarks, intensity: float) -> Image.Image:
    """眼下区域局部提亮（黑眼圈）、鼻翼两颊局部降红（泛红），色彩校正，不做结构性修复。"""

def whiten_teeth(image, landmarks, intensity: float) -> Image.Image:
    """嘴唇内轮廓关键点抠出牙齿区域，HSV 降饱和 + 提亮。"""

def slim_face(image, landmarks, intensity: float) -> Image.Image:
    """基于下颌关键点位移场的局部 warp（cv2.remap），轻微像素级拉伸。"""

def enlarge_eyes(image, landmarks, intensity: float) -> Image.Image:
    """基于眼周关键点的局部径向 warp。"""

def apply_beauty(image: Image.Image, level: int, enable_reshape: bool) -> tuple[Image.Image, list[str]]:
    """编排入口：检测一次关键点；失败则原样返回 + 告警。
    按顺序执行 磨皮/美白/瑕疵柔化（level=0 时整体跳过）；
    enable_reshape=True 时追加 牙齿美白 + 瘦脸 + 大眼（复用同一强度值）。
    """
```

### `config.py`（新增）

```python
BEAUTY_LEVELS = {
    0: ("关闭", 0.0),
    1: ("自然", 0.35),
    2: ("标准", 0.65),
    3: ("较强", 1.0),
}
DEFAULT_BEAUTY_LEVEL_ID = 1
```

说明：五官微调与肤色类效果共用同一强度档位（用户已确认倾向单一强度调节，避免两套参数增加认知负担）。若用户选择「关闭」档位同时又打开五官微调开关，效果强度为 0（自然抵消），不做额外特殊处理。

### `service.py`（修改）

`process_photo()` 新增两个参数：

```python
def process_photo(input_path, photo_size, background_color=(255, 255, 255),
                   brightness=1.05, contrast=1.08,
                   beauty_level: int = DEFAULT_BEAUTY_LEVEL_ID,
                   enable_facial_reshape: bool = False) -> PhotoResult:
```

处理顺序（新增步骤加粗）：

1. `straighten_portrait`
2. `detect_and_crop_face`
3. **`apply_beauty`**（新增，在裁剪之后、抠图之前）
4. `remove()`（rembg 抠图）
5. `trim_body_below_shoulders`
6. `widen_shoulder_band`
7. 背景合成
8. `enhance_portrait`（既有画质增强，保持不变）
9. 亮度/对比度调整

**为什么在抠图之前做美颜**：瘦脸/大眼是几何形变，如果在抠图合成之后再做，会导致人像轮廓与已经计算好的 alpha 蒙版边缘错位，产生描边瑕疵。放在抠图之前，rembg 会基于形变后的几何重新生成一致的轮廓蒙版。肤色类色彩校正对背景不敏感，提前执行没有副作用。

`enable_facial_reshape=True` 时，`apply_beauty` 固定追加一条告警到返回的 warnings 列表：

> "已启用五官微调（瘦脸/大眼/牙齿美白），此类照片可能不符合护照/身份证等官方证件照『真实反映本人相貌』的要求，仅建议用于简历照等非官方场景。"

### `cli.py`（修改）

在背景颜色选择之后、相纸尺寸选择之前，新增两个菜单：

```python
beauty_level = choose_from_menu(
    "请选择美颜强度：",
    {k: v[0] for k, v in BEAUTY_LEVELS.items()},
    default=DEFAULT_BEAUTY_LEVEL_ID,
)
enable_reshape = choose_from_menu(
    "是否开启五官微调（瘦脸/大眼/牙齿美白）？",
    {1: "否（默认，推荐用于官方证件照）", 2: "是（仅建议非官方场景，如简历照）"},
    default=1,
) == 2
```

### `webui.py`（修改）

在 `bg_dd` 下拉框之后新增：
- `beauty_dd = gr.Dropdown(label="美颜强度", choices=[...], value="自然（默认）")`
- `reshape_cb = gr.Checkbox(label="五官微调（瘦脸/大眼/牙齿美白）", value=False, info="⚠️ 可能不符合官方证件照真实性要求，仅建议非官方场景使用")`

`generate()` 签名新增 `beauty_label, enable_reshape` 参数，解析后传入 `process_photo()`；`run_btn.click` 的 `inputs` 列表同步增加这两个组件。

## 错误处理

与项目现有风格一致：`apply_beauty` 及内部所有函数**不抛异常影响成图流程**。关键点检测失败（`detect_face_mesh` 返回 `None`）时，`apply_beauty` 直接返回原图 + 一条告警（"未检测到清晰人脸关键点，已跳过美颜处理"），复用现有 `warnings: list[str]` 机制。

## 测试计划

- `tests/test_beauty.py`（新增，无模型依赖，参照 `test_portrait_fill.py` 风格）：
  - 用构造的假关键点坐标测试 `build_skin_mask` 的区域范围
  - 测试 `smooth_and_whiten_skin` / `reduce_blemishes` 在 `intensity=0` 时输出与输入一致（幂等性）
  - 测试 `apply_beauty` 在 mock `detection.detect_face_mesh` 返回 `None` 时原样返回图像并附告警
  - 测试 `BEAUTY_LEVELS` 强度映射与 `slim_face`/`enlarge_eyes` 在 `intensity=0` 时的幂等性
- `tests/test_detection.py`（扩展）：仿照现有降级测试模式，为 `detect_face_mesh` 补充"模型不可用时返回 None"用例
- 手动验证：实现完成后启动 WebUI（`photolayout --web`），用真实照片测试三档强度 + 开启/关闭五官微调的实际效果，重点检查是否出现"塑料脸"、warp 边缘瑕疵、牙齿区域误伤嘴唇

## 风险与取舍

- 位移场 warp（瘦脸/大眼）在人脸角度较大或部分遮挡时可能产生形变瑕疵，`apply_beauty` 应对关键点整体置信度做合理性检查，效果不理想时宁可跳过而非强行输出畸变图像。
- 磨皮强度过大会出现"塑料感"，`BEAUTY_LEVELS` 的数值需要结合真实照片测试迭代微调，设计文档中的强度值为初始估计，实施阶段可能调整。
