---
name: material-sourcing
description: 按主题检索免费可商用的图片和视频素材，在对话里给出预览、规格与授权信息，按用户指令筛掉不合适项，并把选中的素材存入 Studio 工程素材库或媒体库。用于找素材、搜图片、搜视频、找空镜/B-roll、补充画面素材，或剪辑前先建一个可用素材池。
requiredTools:
  - create_project
  - list_projects
  - probe_image_metadata
  - probe_video_metadata
  - sync_materials
  - list_materials
  - inspect_materials
  - list_media
  - get_media
  - request_file_upload
  - confirm_file_upload
---

# 找素材（Material Sourcing）

> 素材获取一律走本地采集脚本 `material_crawler.py`（P0–P5，负责检索、下载、校验、去重）。
> 本文件只负责：把本地文件展示给用户、按指令筛选、转存并登记进工程素材库。

整个流程只有四步：**采集 → 展示 → 按用户指令筛选 → 存入素材库**。
不要在这一步剪辑时间线，也不要在用户没确认前把素材写进工程。

## 1. 先确定检索条件

从用户的话里提取，缺失时用默认值，不要追问：

| 条件 | 默认 |
| --- | --- |
| 主题关键词 | 用户原话；中文主题翻成 2-3 组英文关键词 |
| 素材类型 | 图片 + 视频 |
| 候选数量 | 8 条（约各 4 条） |
| 画幅 | 抖音/竖屏/口播 → portrait；横屏/公众号 → landscape；否则 any |
| 授权 | 只要 CC0 / CC BY / Mixkit Free License |
| 时长 | 单段视频优先 ≤ 20s（短视频素材） |

## 2. 获取素材（强制调用本地武器库）

不要手写爬虫，也不要只拿远端 URL。直接在终端运行：

```bash
python C:\Users\26808\.trae-cn\skills\material-sourcing-crawler\scripts\material_crawler.py --q "night city" --name "城市夜景" --videos 3 --images 2 --orientation portrait --out "E:\Trae_Video_Workspace\inputs\{任务时间戳}" --json
```

- 脚本自动完成 P0–P5：检索、下载、MD5 去重、图片/视频校验、生成 `manifest.json`。
- 图片默认 `--image-format jpg`，直接产出抖音可发布的 JPG；需要保留源格式时传 `--image-format auto`。
- 视频无音轨时 manifest 会标记 `has_audio=false`；剪辑阶段必须垫入 `E:\Trae_Video_Workspace\bgm.mp3`。
- 中文主题先翻成英文检索词；`--name` 只控制文件名/目录。
- 脚本失败时按返回的 `F-xx` 错误码查 `D:\00_skiill_ku\01_crawler\skills\web-scraping\05_failure_taxonomy.md`，不要反复重试同一请求。
- 补充通道：用户存量素材用 `list_media` / `get_media`；完全没有合适实拍时才考虑 `generate_image` / `generate_video`。

**禁止**：伪造素材；抓取他人抖音/YouTube 成片；使用带水印、付费预览、来源不明的素材。

## 3. 在对话里展示候选

读取 `manifest.json`，按编号给表格；用本地 `abs_path` 作为预览入口，远端 URL 只留在 manifest 里溯源：

```
「城市夜景」已下载 5 个本地素材（Mixkit Free / CC0）：

| # | 类型 | 本地文件 | 规格 | 时长 | 授权 |
|---|------|----------|------|------|------|
| 1 | 图片 | 城市夜景_竖屏_图片_01.jpg | 683×1024 竖 | - | CC0 |
| 2 | 视频 | 城市夜景_竖屏_视频_03.mp4 | 720×1280 竖 | 14.3s | Mixkit Free |

要哪几条？可以说编号（如「1、3、5」），也可以说条件（如「只要竖屏视频」「第 2 条裁成 9:16」）。
```

- 标明横/竖；横屏素材用于抖音时要提示会裁切。
- `has_audio=false` 的视频要在候选表里直接标注「无音轨，剪辑时垫 BGM」。
- CC BY 素材要提醒发布文案里保留署名。
- 最多一次展示 10 条，避免刷屏；用户要更多再跑一次脚本换关键词。

## 4. 按指令筛选

- 「1、3、5」→ 按编号取。
- 「只要视频」「不要带人的」「第 2 条换掉」→ 按条件过滤。
- 用户没明确说「全部要」时，不要默认全存。
- 筛完先复述一遍最终清单（编号 + 标题 + 类型），再进入保存。

## 5. 存入素材库

### 5.1 选目标工程

- 用户指定了工程 → `list_projects` 找到对应 `project_id`。
- 没有指定 → `create_project` 新建：
  - `name`: `素材库-<主题>-<YYYYMMDD>`
  - `description`: 注明来源与授权
  - 画布：抖音/竖屏 `1080×1920`、`#000000FF`；横屏 `1920×1080`；用户未指定画幅时不传 `canvas`。

### 5.2 读取 manifest（不重复探测）

- 脚本已在本地完成尺寸、时长、音轨校验；直接使用 `manifest.json` 里的
  `width` / `height` / `duration_s` / `has_audio`。
- 只有 manifest 缺字段、文件被替换或需要重新转码时，才重新 probe；probe 需要公网 URL，
  所以顺序是「先转存拿 URL，再 probe」。

### 5.3 登记进工程素材库

本地文件必须先按 5.5 转存到 `assets.aitoearn.cn`，拿到 URL 后再 `sync_materials`；
`source` 与 `url` 都使用转存后的地址，不要直接用 rawpixel/Mixkit 的远端直链。

`sync_materials` 一次最多 100 条：

```json
{
  "project_id": "<project-id>",
  "materials": [
    {
      "name": "城市夜景-03-Mixkit",
      "source": "https://assets.aitoearn.cn/<uid>/publish/media/<yyyymm>/<file>.mp4",
      "url": "https://assets.aitoearn.cn/<uid>/publish/media/<yyyymm>/<file>.mp4",
      "type": "video",
      "duration_ms": 14290,
      "width": 720,
      "height": 1280
    }
  ]
}
```

- `duration_ms` 用 manifest 的秒数 × 1000 取整；`width/height` 用 manifest 实测值。
- 视频必填 `duration_ms`、`width`、`height`；图片必填 `width`、`height`。
- 名称统一 `<主题>-<两位序号>-<来源>`，方便后续在时间线里找。

### 5.4 写后校验

`list_materials` 确认状态为 `complete`；必要时 `inspect_materials` 看详情。
给用户回一张结果表：编号 / 素材名 / 素材 ID / 类型 / 规格 / 状态。
失败的条目说明原因，不要假装成功。

### 5.5 可选：存进媒体库（跨工程复用）

只有用户明确说「存到我的素材库 / 媒体库 / 以后还要用」时才做：

1. 直接使用 `manifest.json` 里的本地文件（脚本已下载，无需再下载）。
2. `request_file_upload { filename, size, mimeType, type: "userMedia" }`。
3. `curl -X PUT "<uploadUrl>" -H "Content-Type: <mimeType>" --data-binary @<localFile>`。
4. `confirm_file_upload { assetId }`。
5. `list_media` 校验，回报 `mediaId` 和可访问 URL。
6. 上传成功后保留本地文件作为母版；不要回显敏感信息。

## 6. 授权与质量规则

- 默认只收 CC0 / CC BY / Mixkit Free License；CC BY 必须能保留署名。
- NC（非商用）、ND（禁止改编）、来源不明 → 不默认收；用户坚持时要明确风险。
- Openverse 返回的 `width/height` 是原图尺寸，但 `url` 可能是较小 rendition；**以 manifest 实测值为准**。
  竖屏素材实测宽度 < 720 或高度 < 1280 时提示「清晰度偏低」。
- 同一 URL / 同一素材只存一次。
- 素材直链以后可能 403/过期；编辑或发布前若失效，用 `update_materials` 更新，
  不要重新 `sync_materials` 造成重复。

## 7. 失败处理

- 脚本返回 `F-01` / `F-02`：网络、403 防盗链或 429 限流。按 `05_failure_taxonomy.md` 处理，不要手写重试。
- 脚本返回 `F-03`：空壳/软拦截或空结果。换英文同义词或换源，最多 2 次。
- 脚本返回 `F-17`：单条文件校验失败。跳过该条，继续其余素材，不要整批失败。
- 脚本整体失败：读 stderr 里的 `F-xx` 与原因，修正后重跑一次；仍失败就如实报告，不要伪造成功。
- 保存部分成功：先回报已成功的，再列失败项和原因。
