# 飞书最小平替方案（无 lark 插件的客户端）

> 状态：DISCOVERED 方案设计，未在无人值守期间创建应用或调用任何接口。

## 思路
用飞书开放平台自建应用 + 三个最小技能，覆盖 80% 高频场景；其余 19 个 lark 技能按需再补。

| 最小技能 | 对应 OpenAPI（文档名） | 所需权限点（示例，落地时按官方文档核对） |
|---|---|---|
| 发消息 | 发送消息 `im/v1/messages` | im:message:send_as_bot |
| 读写云文档 | 文档块 `docx/v1/documents/*/blocks` | docx:document、docx:document:readonly |
| 读写电子表格 | 工作表 `sheets/v3/spreadsheets/*` | sheets:spreadsheet、sheets:spreadsheet:readonly |

## 落地步骤（需人工授权）
1. 开发者后台创建企业自建应用，拿 app_id/app_secret，存环境变量 `FEISHU_APP_ID/FEISHU_APP_SECRET`，禁入库。
2. 申请上表权限点，管理员审批。
3. 用 tenant_access_token 流程封装一个 stdio MCP（Python FastMCP 或等价物），仅暴露 3 组工具。
4. 在测试群/测试文档联调，成功后再登记进 CAPABILITY_REGISTRY C11 并把状态改 PASS。

## 边界
- 审批/日历/多维表格/视频会议等不在最小集；需要时按同一模式增量加工具。
- 无人值守不创建应用、不完成授权、不发真实消息。
