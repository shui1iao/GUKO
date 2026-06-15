# Changelog

## [0.1.22] - 2026-06-15

- 地区识别可选对接 Kulin/Komari 面板 GeoIP 结果，减少与面板显示不一致。
- 优化地区识别公开 API 回退顺序。
- 修复 VLESS 安装自动输入的换行处理。

## [0.1.21] - 2026-06-15

- 更新地区识别数据库来源，优先使用更新的 IP 地理位置数据。
- Docker 发布镜像补充版本标签，并确保版本 tag 与 latest 指向同一发布镜像。

## [0.1.20] - 2026-06-05

- 将 TW 地区节点的默认旗帜显示为 🇨🇳。
- 地区识别优先对齐 Kulin/Nezha 使用的 GeoIP 结果。

## [0.1.19] - 2026-06-04

- 节点配置里的 VLESS/SS/AnyTLS 等节点链接改为可复制的代码块格式。
- 恢复测试结果报告链接为普通链接展示。

## [0.1.18] - 2026-06-04

- 优化测试结果里的报告链接展示，改为可直接复制的代码块格式。

## [0.1.17] - 2026-06-04

- 修复 VLESS 安装/查看逻辑：已有 VLESS 配置时识别任意 inbound，不再只检查第一个 inbound。
- 避免在目标机已有非 VLESS 的 Xray 配置时被 GUKO VLESS 安装覆盖，改为提示冲突并退出。
- 修复 Xray-VLESS-Manager 在缺少 `geoip.dat` 的机器上因 `geoip:private` 导致启动失败的问题。

## [0.1.16] - 2026-06-04

- NodeQuality 完成消息不再输出调试用的“原始报告接口”。
- 保持 NodeQuality 选择页默认空选，由用户自行选择项目或点击全选。

## [0.1.15] - 2026-06-04

- 修复 VLESS 半安装状态误判。
- 优化 VLESS 默认端口冲突处理。

## [0.1.14] - 2026-06-03

- 优化节点结果输出格式。
- 修复 VLESS 重复安装问题。

## [0.1.13] - 2026-06-02

- 修复 NodeQuality 结果链接可能被 curl 进度数字污染，确保只保留有效 32 位 token。
- 完整 NodeQuality / 全选任务只发送总结果链接，不再发送分项图片；单选或部分选择仍会发送对应分项图片。
- 修复 NodeQuality 历史记录丢失关键链接的问题，优先保留总结果、Report.Check.Place 分项报告和 Geekbench 链接。
- 修复 NetQuality 在部分机器的 TCP 大包延迟阶段卡住导致空结果的问题，为探测步骤加入超时保护。
- 保留官方 NodeQuality 生成的结果链接，不再二次上传空包或坏包生成无效链接。

## [0.1.12] - 2026-06-02

- 新增 VLESS 与 Snell 管理入口；VLESS 安装可选择纯 VLESS 或 Vision + Reality。

## [0.1.11] - 2026-06-02

- 回退 Check.Place 报告渲染为原 Python/Pillow 终端网格方案，移除实验性的浏览器截图渲染。

## [0.1.10] - 2026-06-01

- 移除任务队列模式，点击测试后直接启动后台任务；同一服务器同类任务运行中时直接提示。

## [0.1.9] - 2026-05-28

- 新增 SS-Rust 与 AnyTLS 管理入口，支持安装/更新检测与查看配置。

## [0.1.8] - 2026-05-22

- 移除老用户 Compose project 改名迁移脚本，避免把一次性改名流程误认为日常升级步骤。
- 保留新版 Compose 的 `name: guko`，新部署会直接显示为 `guko`；老部署正常更新镜像不受影响。

## [0.1.7] - 2026-05-22

- 增加老用户 Compose project name 迁移脚本，稳定处理从目录名 project 迁移到 `guko` 的容器名冲突。
- README 增加老部署升级说明，明确保留宿主机挂载数据。

## [0.1.6] - 2026-05-22

- Docker Compose 示例显式设置项目名为 `guko`，避免部署目录名影响管理面板显示。
- 更新 README 部署说明，说明 Compose project name 会固定显示为 `guko`。

## [0.1.5] - 2026-05-20

- 修正文档中的安全表述，补充 Issue 模板，并完善 Release 附件。

## [0.1.4] - 2026-05-20

- 加入基础 CI、防泄密检查、Actions Node24 兼容设置和本地项目健康检查。

## [0.1.3] - 2026-05-20

- 补齐中英双语 README、统一部署说明，并加入本地 release helper。

All notable changes to this project are documented here.

## [0.1.2] - 2026-05-19

- 修复 Release workflow YAML，确保 tag 发布会自动用 CHANGELOG 生成 Release notes。

## [0.1.1] - 2026-05-19

- 维护版本发布流程：新增 CHANGELOG 与 Release Drafter；Docker 发布保留 latest、版本号和 sha 标签。
