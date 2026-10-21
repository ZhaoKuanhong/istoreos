# iStoreOS Router for Home Assistant（ubus 版）

[English](README.md) | [中文](README_zh.md)

本项目 fork 自 [SJMTIII/istoreos](https://github.com/SJMTIII/istoreos)。2.0.0 将旧版 `/cgi-bin/luci/rpc/*` 接口迁移为 **`/ubus` JSON-RPC 2.0**，不再依赖 `luci-mod-rpc`。

## 安装与升级

1. 在 HACS 自定义仓库中添加 `https://github.com/ZhaoKuanhong/istoreos`，类型选择 **Integration**。
2. 安装后重启 Home Assistant。
3. 在“设置 → 设备与服务”添加 iStoreOS Router，填写路由器 IP／主机名（可带端口）或 `http://`／`https://` 基础地址，以及路由器账号密码。不要填写 `/cgi-bin/luci/...` 路径。

从原仓库切换时，先移除原 HACS 仓库／下载条目，**保留集成配置**，再安装本 fork。两者域名都为 `istoreos`，不能同时安装。既有配置条目和实体 ID 保持兼容，重启后加载新实现。也可以手动用本项目的 `custom_components/istoreos/` 替换 HA 配置目录中的同名文件夹后重启。

## 路由器要求

需要 `rpcd` 服务及 uhttpd 提供的 `/ubus` 入口（`uhttpd-mod-ubus`）。已确认 iStoreOS 24.10.8 的该入口可达；新集成仍需完成带认证的实机验证。安装集成不会修改路由器设置，HTTPS 证书验证保持开启。

账号需要相应的 ubus 权限：

| 功能 | 对象／方法 |
| --- | --- |
| 登录 | `session.login` |
| 运行时间、负载、内存 | `system.info` |
| 固件信息 | `system.board` |
| WAN IPv4 | `network.interface.wan.status` |
| 在线设备数、连接数 | `file.read`，读取 `/proc/net/arp` 和 `/proc/sys/net/netfilter/nf_conntrack_count` |
| 重启按钮 | `system.reboot` |
| 重连 WAN 按钮 | `network.interface.wan.down`、`.up` |

`file.read` 还需要对应文件的读取 ACL，以及 rpcd 文件插件。可选指标缺少方法、文件或权限时显示不可用，不影响系统状态。按钮需要写入权限。本项目不会替账号增加路由器权限。

## 行为说明

- 每 60 秒统一采集一次，所有传感器共享结果，避免逐个实体重复请求。
- 会话失效后自动重新登录并重试一次；分别检查 HTTP、JSON-RPC 和 ubus 错误；日志不记录密码或会话令牌。
- 内存从字节换算为原有 MiB 数值，已用内存按总量减可用量计算。负载按内核 16 位定点数换算。
- 在线设备数沿用原定义：`br-lan` 上完整的 IPv4 ARP 条目数。这是估计值，不是 DHCP 设备列表，也不适合作为可靠的在家判断。
- WAN IP 为 `wan` 接口分配的 IPv4，存在 NAT 时可能是私网地址；不再通过外部服务查询公网 IP。
- 重启和重连按钮直接调用 ubus，不再执行 shell。按钮仅在本地模拟服务中测试，测试不会重启或断开实际路由器。

若出现 404，检查 HA 能否访问路由器 `/ubus`。浏览器能登录 LuCI 不代表 ubus 已开启。密码错误会单独提示；既有条目密码变化时可删除并重新添加集成。

## 测试

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

测试使用本机 aiohttp HTTP 服务，覆盖登录、会话续期、ACL 拒绝、响应校验、单位换算、可选指标和按钮调用，不需要路由器密码。完整 HA 运行和带认证的实机测试不在该测试范围内。
