# 当前本地代理读取/新装边界

SS/AnyTLS已改为Kat，一个入口读全部受支持实例；Snell仍走原固定INI快照、本地-v和原Manager安装路径，行为不变。VLESS只保历史名称/被动URI显示，新回调和执行能力均已移除；不卸载远端服务、不改旧history。

## Kat读取

目标只使用已有POSIX shell/systemctl/proc/coreutils；不运行Manager view/status/check、Kat程序、Python/jq或节点API，不写临时配置或自动补依赖。发现标准/kat-*单位并用实际Kat进程补自定义服务，effective unit、exe/cgroup/绝对run CONFIG链及前后快照须一致。每文件最多1MiB、配置总量4MiB、32实例/路径，超限/未知/权限/截断均固定错误；不泄快照或编码凭据。文件仅是磁盘配置，不保证内存已reload或连接可用。完全任意且停止的自定义单位若无可发现锚定，不在支持范围，不能据此证明全机未安装。

旧后端inactive/disabled残留不取代可靠Kat；旧后端运行、仅旧痕迹、无主配置或权威冲突拒绝安装。多个inbound/多个unit逐项输出；2022读ss.key，2017读ss.password，AnyTLS读anytls.password，非空users拒绝。未知TLS/ACME不猜客户端校验/SNI，标unsupported；不读私钥。节点完整分页并保存本次完整私有文本，历史重发不SSH或查新。

## Kat新安装

主入口/旧ensure或install回调只读。完整确认所选协议不存在后另发明确安装确认；绑定用户/chat/服务器/协议，10分钟单次有效，旧/伪造确认拒绝。点确认后重新完整发现、前置检查及同任务身份冻结，下载前再次guard/hash；竞态发现已有节点只读或停止，不覆盖。

仅新装时冻结官方Kat-Manager main准确commit的kat.sh/kat_manager.py/kat_config.py并校wrapper pins，CLI为install ss|anytls --host ...，非旧stdin菜单。已有合法共享core只复用；无core才冻结Kat-Server正式latest binary/SHA。缺root/Linux amd64/systemd/Python3/curl等前置停止，不装依赖、不update已有内核。安装后不用文本猜成功，重新只读采集真实unit/config和内核身份；失败不自动升级/重试。Manager仅建标准单协议节点，不接管自定义第二实例。

## 源码回归契约（发行时离线运行）

新Kat契约在tests/test_kat_proxy.py与test_proxy_client_formats.py，含多实例/users/TLS/编码/旧痕迹/有界帧/无Python读取/确认和安装身份。原Snell的只读副作用/版本/传输/安装交互安全断言保留。删除功能的旧VLESS正向安装期望改为明确拒绝、历史保留断言，不为追绿放宽安全。
