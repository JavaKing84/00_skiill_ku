# 03_video 技术情报雷达（能力补齐专项）

- 版本：1.0（2026-11-22）
- 调研方式：GitHub 仓库页面实查（`stargazerCount`）+ shields.io license 徽章读取，**非记忆值**；星数为 2026-11-22 当日快照，会随项目增长变化。
- 选型原则（硬约束）：**CPU 本地可跑 > Windows 兼容 > GitHub 高 Star > 可对接现有 FFmpeg 流水线**。
  必须 N 卡才能跑的模型一律标记【GPU可选，默认关闭不启用】，不进入默认依赖。
- 集成层级定义：
  - **直接集成**：装依赖或拷代码即可进 `scripts/`，默认链路可用。
  - **借鉴思路本地实现**：项目本身过重/许可/兼容不合适，只吸收数据模型或算法思路，自己写轻量实现。
  - **不采用**：不安装、不引用，只记录为技术观察。
- 本轮全程**不渲染任何 mp4**，只产出分析数据（csv/json/md）与可被后续剪辑任务 import 的函数。

---

## 0. 环境基线（实测）

| 项 | 实测值 | 结论 |
|---|---|---|
| Python | 3.14.7（`D:\00_skiill_ku\.venv`） | 很多 ML 库（torch/tensorflow/insightface）没有 3.14 wheel，这是本轮排除重型库的硬原因 |
| OpenCV | cv2 5.1.0（含 `FaceDetectorYN` / `FaceRecognizerSF`） | 可跑 YuNet + SFace，纯 CPU，无 torch |
| onnxruntime | 1.32.0 | **必装**：YuNet 检测实际由 onnxruntime 直接推理 + 自行解码（OpenCV 5.1 的 `FaceDetectorYN.detect()` 实测返回空人脸，见 §1④） |
| PySceneDetect | 0.7.3 | 模块2 直接复用 |
| FFmpeg / ffprobe | 9.0.2 essentials | 音频诊断、抽帧、filter 字符串生成 |
| numpy | 2.5.5 | 音频/帧差计算 |
| 缺失 | torch / tensorflow / insightface / deepface / facenet-pytorch / pandas / scikit-learn / librosa | 均不进必装依赖 |

> 结论：在 Python 3.14 + Windows + 无独显的环境里，**能稳定落地的路线只有 OpenCV-DNN(ONNX) + PySceneDetect + FFmpeg + numpy**。
> 其余万星级项目不是不好，而是"装不上/要 3.10+torch/CUDA"。这一点在下面每张表里都按事实记录。

---

## 1. 缺陷1：画面人物人脸检索筛选

### ① 业务痛点
`win_asr.py` 只能回答"谁在说话"，无法回答"画面里出现了谁"。实际踩坑：
- 音频是韦布台词，画面却是王金/韦布父亲，成片出现"说话的人不在画里、画里的人不说话"，观众直接出戏。
- 靠人工写死时间白名单（`validate_45s.py` 的 `WHITELIST_RANGES`）维护成本极高，换一部片整套失效。
- 无法批量筛出"只有目标主角、黑名单人物不出现"的干净镜头。

### ② 期望能力与 IO
- 输入：源视频 + 参考头像目录（`assets/elephant/faces/target/`、`.../blacklist/`）。
- 输出 CSV（固定六列）：`start,end,target_person_hit,blacklist_person_hit,face_count,confidence`
- 逻辑：按 `--window` 秒聚合；每窗抽 `--fps` 帧做人脸检测 + 特征比对；`confidence` 取该窗内最高余弦相似度；背光/侧脸/遮挡靠相似度阈值 + 最小人脸像素过滤降误检。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 人物检索 | deepinsight/insightface | 30282 | 未标注（代码 MIT 风格，**模型权重另有非商用限制**） | CPU 可（onnxruntime）/ GPU 可选 | 差：`pip install insightface` 常需 C++ Build Tools，Python 3.14 无预编译轮子 | 优点：ArcFace 精度业界第一梯队；缺点：安装重、权重许可需逐项确认、模型需另下 | 不采用（仅文档备选） |
| 人物检索 | serengil/deepface | 23721 | MIT | CPU 可，但依赖 TensorFlow/Keras | 差：TF 无 3.14 轮子，装完动辄 1GB+ | 优点：API 极简、封装多种模型；缺点：重、启动慢、Windows 上 TF 版本敏感 | 不采用 |
| 人物检索 | timesler/facenet-pytorch | 5177 | MIT | CPU 可 / GPU 可选 | 差：需 torch，3.14 无官方轮子 | 优点：MTCNN+InceptionResnet 经典组合；缺点：torch 体积大、推理慢 | 不采用 |
| 人物检索 | opencv/opencv_zoo（YuNet + SFace） | 1141 | Apache-2.0（权重随仓库，商用前需复核） | **纯 CPU**，ONNX，cv2 DNN 直跑 | **好**：两个 onnx（233KB + 37MB）放本地即可，无编译 | 优点：零 torch、开箱即用、单帧 20–40ms；缺点：侧脸/远距离小脸召回明显低于 ArcFace，SFace 精度中等 | **直接集成**（`person_scan.py`） |
| 人物检索 | solomonneas/reelgrep | 8 | MIT | CPU | 好（Python + ffprobe） | 优点：ffprobe 元数据 + 抽帧 + 联系人表 + FTS5 字幕检索 + 可插拔检测器的工程范式；缺点：星数极低、维护弱、无成熟人脸身份库 | 借鉴思路（索引与抽帧设计），不引入代码 |
| 人物检索 | ahumanflourish/takeseek | 0 | MIT | CPU（依赖外部 VLM） | 一般 | 优点：转写+视觉描述联合索引；缺点：0 star、需在线模型、与本机离线约束冲突 | 不采用 |

### ④ 集成决策
- **直接集成 OpenCV Zoo 的 YuNet（检测）+ SFace（128 维特征）**：YuNet 用 **onnxruntime 直接推理并自行解码 + NMS**（本机 OpenCV 5.1 新 graph engine 的 `cv2.FaceDetectorYN.detect()` 实测返回 retval=1 但人脸矩阵为空）；特征与对齐用 `cv2.FaceRecognizerSF`。纯 CPU。
- 身份判定用**余弦相似度阈值**（默认 0.363，SFace 官方 LFW 阈值），并叠加"最小人脸像素 48px""最小检测分 0.7"两道门。
- 风险边界（必须写进 SKILL.md）：
  - 背光、强侧脸、口罩/手遮挡、远景小脸（<48px）会漏检；同一演员不同年龄/妆造会掉相似度。
  - 黑名单里"王金"与"老人"在本片是同一角色，配置需合并，否则重复计数但不影响命中判断。
  - 相似度阈值是**经验值**，换片必须用 20–30 个样本重新校准；不做"100% 识别"承诺。
- 替代降级：无参考头像时，脚本支持 `--build-gallery` 从已知镜头自动裁脸建库，人工只需给裁出的脸贴名字。

---

## 2. 缺陷2：镜头语义解析（景别 / 运动 / 长短镜头）

### ① 业务痛点
- 每条镜头是特写/中景/远景全靠人眼标；`shot_detect.py` 只给切点，不给语义。
- 没有 `motion_score`，无法区分"静态长镜头"和"手持抖动快切"，AI 排片容易把碎镜头硬拼成"乱剪"。
- 没有客观镜头标签，`validate_45s.py` 只能校验时长，无法校验"情绪—景别"是否匹配。

### ② 期望能力与 IO
- 输入：源视频 + 时间窗。
- 输出 JSON：`shot_id,start_time,end_time,shot_scale[特写/近景/中景/远景],face_area_ratio,motion_score,is_long_shot`
- 实现：PySceneDetect 切边界 → 每镜抽 3–5 帧 → YuNet 求最大人脸面积占比 → 帧差（灰度缩略图 MAE）求运动量 → 时长阈值判长镜头。
- **不调用 VL 大模型**，保证 1080p 下每秒可处理数十帧。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 镜头切分 | Breakthrough/PySceneDetect | 5616 | BSD-3-Clause | CPU | 好（纯 Python + OpenCV，已装 0.7.3） | 优点：确定性、快、可复现、支持 ContentDetector/ThresholdDetector；缺点：不懂景别与运动语义 | **直接集成**（已在 `shot_detect.py`，模块2 复用） |
| 镜头切分 | soCzech/TransNetV2 | 1083 | MIT | 【GPU可选，默认关闭不启用】，CPU 可跑但慢 | 一般：需 TensorFlow 1.x/2.x 兼容层 + 权重 | 优点：转场/闪光/淡入淡出鲁棒性优于阈值法；缺点：依赖 TF、权重另下、CPU 推理慢 | GPU 可选，不进默认链路 |
| 镜头语义 | eternityspring/reelbench-skills | 1247 | Apache-2.0 | 无（文档/Skill 集合） | 好 | 优点：AI 视频拆解方法论与字段约定可借鉴；缺点：不是可执行库，无可复用算法 | 借鉴思路（标签字段设计） |
| 镜头语义 | JuneYaooo/rea-video | 12019 | Apache-2.0 | 无（方法论/prompt） | 好 | 优点：逐镜头逆向、VIDEO.md 结构化输出范式；缺点：面向"复刻拍摄"，不做本地数值判定 | 借鉴思路（输出结构），不引入 |
| 镜头语义 | 无可靠开源"景别分类"库（关键词检索命中均为无关论文/小项目） | — | — | — | — | 说明：景别工业界多靠人脸/人体框占比规则，而不是端到端分类器 | 自研规则实现 |

### ④ 集成决策
- 直接复用 PySceneDetect（已安装、已验证）+ 自研规则层：`face_area_ratio` 阈值分级。
- **景别阈值（本片标定，写进 SKILL.md）**：`≥0.22 特写`、`0.12–0.22 近景`、`0.05–0.12 中景`、`<0.05 远景`；无脸镜头记 `远景` 并置 `face_area_ratio=0`。
- `motion_score`：镜头内相邻采样帧灰度 MAE 归一化到 0–1；>0.25 视作明显运动/手持，<0.05 视作静态。
- 局限：人物完全背身、全黑/极暗画面、纯空镜无法判景别（只能给远景+低置信）；快速摇镜会让 motion_score 虚高。

---

## 3. 缺陷3：叙事连贯性校验 + J-cut 分级

### ① 业务痛点
- `validate_45s.py` 只有时间白名单 + 音频能量，无法读镜头语义 JSON 校验"情绪组接顺序"。
- J-cut（音频说话人 ≠ 画面主要人物）在《大象席地而坐》里大量存在（画外独白），旧逻辑要么直接 FAIL，要么完全不提示。
- 缺少 block/warn 分级：真错误（黑名单人物入画、支线命中）必须阻断；艺术处理（J-cut、长镜头偏多）只应告警。

### ② 期望能力与 IO
- 输入：结构化时间轴 JSON（兼容 `timeline_45s.json` 的 `sections` 结构）+ 可选 `shot_analyze` JSON + 禁止支线区间。
- 输出 JSON 列表：`error_level ∈ {block,warn}`、`message`、`time_range`；附 `verdict` 与统计。
- 校验项：情绪顺序、J-cut（开关 `allow_jcut`）、禁支线命中、节奏统计（碎镜头过多 / 长镜头滥用）。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 连续性校验 | octimot/StoryToolkitAI | 1084 | **GPL-3.0** | CPU/GPU 均可，需 torch + whisper | 一般：依赖重、含 Resolve 集成 | 优点：EDL/时间轴 + 转写 + 搜索一体化；缺点：GPL 传染、体量大、面向达芬奇工作流，不适合嵌入本 Skill | 不采用（仅看 EDL 模型） |
| 连续性校验 | lmova44-hub/continuityguard | 0 | 未标注 | CPU | 未知 | 优点：短剧人物连续性思路；缺点：0 star、无文档、无发布 | 不采用 |
| 连续性校验 | EditIQ（检索仅命中同名无关仓库） | — | — | — | — | 未检索到可信的"叙事连贯性校验"项目 | 不采用 |
| 时间轴模型 | AcademySoftwareFoundation/OpenTimelineIO | 2108 | Apache-2.0 | CPU | 中：C++ core + Python 绑定，需轮子 | 优点：行业标准 OTIO 模型、可转 EDL/AAF；缺点：依赖重，仅为一个校验脚本引入不划算 | 不采用（未来跨软件协作再评估） |

### ④ 集成决策
- 自研 `validate_narrative.py`：纯规则 + JSON 输入，不引入第三方包。
- J-cut 判定：`video.role` 与 `audio.speaker/role` 不一致，或 `audio.src != video.src` → `warn`（`allow_jcut=True`）／`block`（`allow_jcut=False`）。
- 分级定义：`block` = 必须重剪（黑名单人物入画、禁支线命中、情绪顺序断裂、总时长越界）；`warn` = 可人工放行（J-cut、碎镜头比例高、单镜过长、景别与情绪不匹配）。
- 局限：情绪顺序校验依赖时间轴里人工/上游写的 `emotion` 字段，属于"校验标注一致性"，不是"理解电影"；没有 `emotion` 字段时跳过该项并给出 warn。

---

## 4. 缺陷4：音频混音逻辑碎片化

### ① 业务痛点
每次剪辑手写数百字符 `filter_complex`，ducking/响度/淡入淡出/诊断全硬编码：
- BGM 出场太晚、BGM 盖人声、某句台词音量过小，都要等渲染完人工听才发现。
- 参数散落在 PowerShell/文本里，复用与回归测试都不成立。

### ② 期望能力与 IO
四个纯函数（只返回 filter 字符串/诊断 dict，不落视频）：
1. `audio_ducking(voice_label, bgm_label, threshold, ratio, attack, release)` → filter_complex 片段
2. `audio_segment_normalize(mode="dynaudnorm"|"loudnorm", ...)` → 单轨 filter 链
3. `audio_diagnose(voice_path, bgm_path, speech_windows)` → dict（BGM 入场时间、台词丢失、人声-BGM 响度差、压侧量）
4. `audio_fade_in_out(fade_in, fade_out, total, curve)` → 单轨 filter 链

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 音频处理 | kkroening/ffmpeg-python | 11022 | Apache-2.0 | CPU | 好 | 优点：filter graph 的 Python DSL；缺点：本项目只需字符串拼接，引入后仍要懂 filter 语义，且多一层调试成本 | 借鉴（不装依赖） |
| 音频处理 | jiaaro/pydub | 9805 | MIT | CPU（需 ffmpeg） | 好 | 优点：fade/拼接简单；缺点：解析整段音频到内存，长片吃内存，且 ducking 仍要手写 ffmpeg | 不采用 |
| 音频处理 | slhck/ffmpeg-normalize | 1544 | MIT | CPU | 好 | 优点：loudnorm 两遍法的成熟封装；缺点：是 CLI 包装，无法返回可拼接的 filter 片段 | 借鉴 loudnorm 参数 |
| 音频处理 | KyaniteLabs/kinocut | 277 | Apache-2.0 | CPU | 好（MCP + CLI） | 优点：带 guardrail 的 ffmpeg 编辑 MCP，音频链参数可参考；缺点：整体是服务端形态，嵌进本 Skill 过重 | 借鉴参数与校验思路 |
| 音频处理 | audio-arrange / VEMCP / "mixing" 库 | 未检索到可信项目（搜索结果均为无关仓库） | — | — | — | 命名疑似不存在，不能作为依赖 | 不采用 |

### ④ 集成决策
- 自研 `audio_skill.py`：4 个函数 + 1 个诊断器，全部只用 ffmpeg + numpy，**零新增依赖**。
- 默认参数沿用已实测结论：BGM `-16~-19dB` 垫底、`sidechaincompress threshold=0.03~0.08 / ratio 3~9 / attack 6~10ms / release 380~500ms`、人声 `dynaudnorm` + 整体 `loudnorm I=-16`。
- 局限：`audio_diagnose` 的"台词丢失"是能量阈值判断，不等价于人耳语义；气声/耳语会被误判为丢失，需结合 `speech_windows` 人工确认。

---

## 5. 缺陷5：素材多模态条件检索

### ① 业务痛点
- 只能人工填时间戳找片段；"韦布出镜的中景长镜头、不要王金、台词含满洲里"这种组合条件无法表达。
- whisper 文本检索与画面检索两套割裂，无法联合过滤。

### ② 期望能力与 IO
- 输入：`person_scan_result.csv` + `shot_analyze_result.json` + whisper JSON + 查询条件。
- 输出 CSV：`source,start,end,shot_scale,character_list,dialogue_text,confidence`
- 实现：以 `(source,start,end)` 区间做交叠 join，纯内存过滤；**不解码视频、不建向量库**。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 多模态检索 | ahumanflourish/takeseek | 0 | MIT | CPU + 外部 VLM | 一般 | 优点：转写+视觉描述联合索引，理念对；缺点：0 star、依赖在线模型、无稳定 API | 不采用 |
| 多模态检索 | solomonneas/reelgrep | 8 | MIT | CPU | 好 | 优点：SQLite FTS5 字幕检索 + 抽帧 + 联系人表，正好是"本地轻索引"范式；缺点：无人物身份与景别字段 | 借鉴思路（FTS5/区间索引），自研 CSV join |
| 多模态检索 | iiPercy/ClipCatalogue | 未核实（星数抓取失败） | 未知 | 未知 | 未知 | 仅名字相似，无文档可评估 | 不采用 |
| 多模态检索 | Edit-Mind / Cinestar | 未检索到可信项目 | — | — | — | 检索无结果或命中无关仓库，不能作为候选 | 不采用 |

### ④ 集成决策
- 自研 `material_retrieve.py`：区间交叠 + 多条件 AND 过滤；支持自然语言式的结构化条件（人物/景别/长镜头/台词关键词/排除人物）。
- 局限：结果精度完全取决于上游 `person_scan` 与 `shot_analyze` 的精度；不做语义向量检索，同义词需用关键词列表（如"满洲里|大象"）。

---

## 6. 缺陷6：EDL / 时间轴互操作

### ① 业务痛点
- 内部只有自定义时间轴 JSON，无法交给 DaVinci Resolve / Premiere 继续精修。
- 也无法把外部剪辑师给的 EDL 读回来做质检与复用。

### ② 期望能力与 IO
- `timeline_to_edl()`：内部 JSON → CMX3600 `.edl`（`TITLE/FCM/EVENT` 最小子集）
- `edl_to_timeline()`：`.edl` → 内部 JSON
- 只处理 `C`（cut）事件与源/记录时间码，不支持转场/特效/变速。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| EDL 读写 | simonh10/python-edl | 102 | MIT | CPU | 好（纯 Python） | 优点：CMX3600 解析完整；缺点：只读不写、更新时间较早、数据结构需二次转换 | 借鉴字段与解析规则，自研读写 |
| EDL 读写 | iluvcapra/pycmx | 31 | MIT | CPU | 好 | 优点：CMX3600 解析专门库；缺点：星数低、无写出、无时间码帧率灵活配置 | 不采用 |
| EDL 读写 | AcademySoftwareFoundation/OpenTimelineIO | 2108 | Apache-2.0 | CPU | 中（需编译轮子） | 优点：EDL/AAF/OTIO 互转标准；缺点：依赖重，超出"最小可用子集"需求 | 不采用（升级路径） |
| EDL 读写 | octimot/StoryToolkitAI（EDL 模块） | 1084 | GPL-3.0 | CPU | 一般 | 优点：与 Resolve 实战验证过；缺点：GPL、代码与 UI 强耦合 | 不采用 |

### ④ 集成决策
- 自研 `edl_io.py`：手写 CMX3600 解析/序列化（约 200 行），零依赖，支持 24/25/30fps 非丢帧。
- 局限：不支持 dissolve/wipe、不支持多轨音频 EDL（A/V 分离）、不支持 59.94 丢帧时间码；超出子集直接报错而不是静默丢数据。

---

## 7. 缺陷7：成片质量综合巡检

### ① 业务痛点
- 人物扫描、镜头分析、叙事校验、音频诊断分散在 4 个脚本，需要人工逐个跑、人工拼报告；漏跑一项就可能带着黑名单人物或丢台词交付。

### ② 期望能力与 IO
- `quality_check_all.py --video-dir ... --timeline ... --out report.md`
- 一次调用跑完全部检查，输出 `quality_report.md`（含 PASS/WARN/FAIL 总 verdict 与分项表）。

### ③ GitHub 调研（实查）

| 模块名称 | 开源项目 | Star | License | CPU/GPU | Windows适配 | 优缺点 | 集成决策 |
|---|---|---|---|---|---|---|---|
| 质检编排 | lmova44-hub/continuityguard | 0 | 未标注 | CPU | 未知 | 仅可参考"分项 checklist + verdict"报告排版，无可用代码 | 借鉴报告格式 |
| 质检编排 | WyattBlue/auto-editor | 6048 | Unlicense | CPU | 好 | 优点：基于音频/画面静默的自动剪辑，工程成熟；缺点：目标是"自动砍静音"，不是质量巡检 | 不采用 |
| 质检编排 | 03_video 既有 video_qc.py | — | 本项目 | CPU | 好 | 优点：已有黑屏/静音/冻结/时长门禁；缺点：不做人物/叙事/混音 | **复用+编排** |

### ④ 集成决策
- 新写总入口，复用 `video_qc.py` 的指标结论 + 新模块的分析产物；报告格式借鉴 continuityguard 的 checklist 表。
- 局限：总报告是"规则体检"，不替代人眼审片；音频指标好不代表情绪对。

---

## 8. 未核实 / 命名不存在清单（如实记录）

| 名称（任务给定） | 检索结果 | 处理 |
|---|---|---|
| reelgrep | 存在 `solomonneas/reelgrep`，8★，MIT，本地视频检索/抽帧/联系人表/FTS5 | 借鉴思路 |
| TakeSeek | 存在 `ahumanflourish/takeseek`，0★，MIT，早期项目 | 不采用 |
| continuityguard-cli | 仅见 `lmova44-hub/continuityguard`（0★）等派生，无 CLI 发布 | 不采用 |
| EditIQ | 检索命中同名无关仓库，无可信视频叙事项目 | 不采用 |
| Edit-Mind / Cinestar / ClipCatalog / audio-arrange / VEMCP | 检索无结果或仅同名无关仓库 | 不采用 |
| reelbench-skills | `eternityspring/reelbench-skills`，1247★，Apache-2.0，方法论/Skill 集合 | 借鉴字段设计 |
| rea-video | `JuneYaooo/rea-video`，12019★，Apache-2.0，逐镜头逆向方法论 | 借鉴输出结构 |
| pyedl | 未检索到该仓库；实际可用的是 `simonh10/python-edl`(102★) 与 `iluvcapra/pycmx`(31★) | 自研最小子集 |

> 说明：任务里给出的部分项目名可能是产品名/内部代号而非 GitHub 仓库名。这里不做臆测，统一按"检索不到可信项目"处理并给出本地替代方案。

---

## 9. 最终技术栈结论

| 能力 | 采用方案 | 依赖 | 默认开启 |
|---|---|---|---|
| 人脸检测 | OpenCV YuNet (ONNX, 233KB) | onnxruntime + cv2 | 是 |
| 人脸特征 | OpenCV SFace (ONNX, 37MB, 128 维) | cv2.FaceRecognizerSF | 是 |
| 镜头切分 | PySceneDetect ContentDetector | scenedetect | 是 |
| 镜头语义 | 人脸占比 + 帧差规则 | cv2 + numpy | 是 |
| 叙事校验 | 自研规则引擎 | 无 | 是 |
| 混音封装 | 自研 filter 生成 + ffmpeg + numpy 诊断 | ffmpeg | 是 |
| 素材检索 | 自研 CSV/JSON 区间 join | 无 | 是 |
| EDL 读写 | 自研 CMX3600 子集 | 无 | 是 |
| 质检总入口 | 编排以上模块 + video_qc | 无 | 是 |
| 学习型镜头切分 | TransNetV2 | TensorFlow + 权重 | **否（GPU可选）** |
| 深度人脸识别 | insightface / ArcFace | onnxruntime + 权重 | **否（GPU可选）** |

## 10. 权重与许可（下载与存放）

| 权重 | 用途 | 大小 | 下载地址 | 本地路径 | 许可 |
|---|---|---|---|---|---|
| face_detection_yunet_2023mar.onnx | 人脸检测 | 233KB | `https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` | `D:\00_skiill_ku\03_video\models\` | 随 opencv_zoo（Apache-2.0），商用前自行复核 |
| face_recognition_sface_2021dec.onnx | 人脸特征（128维） | 37MB | `https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx` | `D:\00_skiill_ku\03_video\models\` | 同上 |

> 注意：opencv_zoo 用 Git LFS 存储权重，直接访问 `raw.githubusercontent.com` 只会拿到 130 字节的 LFS 指针文件，必须用 `media.githubusercontent.com/media/...`。
> 实测 `media` 地址对大文件（SFace 37MB）限速严重、断点续传易产生损坏文件；成功路径是 HuggingFace 镜像：
> `https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx`
> （用 PowerShell `Invoke-WebRequest -OutFile` 下载，下载后核对大小 38,696,353 字节）。YuNet 233KB 从 `media` 地址可直接下成功（232,589 字节）。
> 这是本轮实际踩到的坑，已写入 SKILL.md。

## 11. 事实与推断分离

- **事实**：Star/License 数字来自 2026-11-22 页面抓取；本机依赖版本来自实际 import；模型可运行性来自实际跑通（见各 demo 输出）。
- **推断**：各项目"优缺点"中关于精度/安装难度的判断，来自官方 README、依赖清单与本机 Python 3.14 环境实测；未做大规模基准测试，不宣称"某模型在某某数据集上高 X%"。
- **未覆盖**：没有对商业闭源工具（达芬奇 Studio、Premiere）做自动化测试；没有做多片源泛化评估。
