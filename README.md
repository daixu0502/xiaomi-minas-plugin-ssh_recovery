# 小米智能存储 SSH 恢复

详细目录、保留例外和部署流程见 [缓存与安装目录](docs/runtime-layout.md)。

## 1.1.11 目录与部署整理

当前版本 **1.1.11**。可重建缓存、普通日志和运行状态使用官方 `tmp/`（链接 `plugintmp/sshrecovery/`）；配置、任务、内核和受保护的权限/SSH 材料保留原持久位置。安装包仅保留必要运行资源，测试仅保留本地。升级不删除用户数据。

## 1.1.10 公共权限组件

当前版本 **1.1.10**。使用公共权限组件 **1.1.1 / API v1**；安装包只含共有部分和自身私有模块，底部动态显示实际组件版本。仅升级较旧的共有组件，不降级、不覆盖其他插件模块。SSH 恢复数据由所属模块迁至 `modules/sshrecovery/var/`。目录布局、授权和兼容策略见 [公共权限组件](docs/privileged-component.md)。

## 1.1.8 修复开机代码版本误判

识别 `.sh` 安装时多出的末尾空行及 CRLF，不再误报为其他版本。只比较实际使用的 worker、Cron 与 systemd 配置，不把旧 Python 应急 CLI 当作开机依赖；保留它供原有应急流程使用。安装确认仅在这些文件确有不同内容时显示替换选项，并指出具体文件。正常情况下显示“已安装（当前版本）”。

## 1.1.7 统一纯 Shell 开机修复

开机 worker 改为纯 Shell，与 nas-root 2.1.0 的 SSH 开启脚本和 `install-ssh-autostart-fix.sh` 嵌入的 `restore-ssh.sh` 完全一致，测试逐字节核对。保留等待真实开机检查、缺失授权恢复、旧 root 目录迁移、mi-shell 服务私有 Bash 映射和 12 次有限复查。网页 API 保持原有实现，安装插件本身不会自动开启 SSH 或覆盖已有开机修复；需明确点击“安装 / 更新开机修复”应用新版 worker。

新旧工具共用登录授权快照与操作锁，保留现有授权、设置和服务；不向原厂校验的源码目录写入运行文件。

## 1.1.6 文字可读性与任务兼容

统一中文字体回退，日志使用 15px 字号与更宽行距，辅助文字不低于 13px；提高浅色及手机深色模式对比度，样式仅作用于插件内部。公共权限组件更新至 1.0.6，定时 Docker 操作在任务总超时内等待事务锁；不重试已发出的 Docker 命令。

## 1.1.5 公钥导入与提示

- 兼容 OpenSSH 公钥换行、SSH2/RFC4716 公钥、UTF-8 BOM 和 Windows UTF-16 文本文件，仍只接受一条经结构及安全长度校验的公钥，拒绝 authorized_keys 选项。
- 公钥模式误选私钥时在本机阻止上传并提示正确导入方式，不会自动切换为私钥提取；多公钥、编码问题等分别显示具体错误。
- 导入错误显示在表单底部并自动进入可视区域，同时提供固定提示。公钥导入失败或取消确认会保留输入，成功后清空；私钥处理后仍立即清理页面输入，不写入磁盘。

## 1.1.4 公共组件兼容

同步公共权限组件 1.0.5，与 Docker 管理、定时任务的优化版本保持一致。SSH 恢复逻辑不变，不自动生成密钥、不自动启用开机修复，也不更改已有密钥材料。

仓库：[xiaomi-minas-plugin-ssh_recovery](https://github.com/daixu0502/xiaomi-minas-plugin-ssh_recovery)。可通过仓库页面的 Code → Download ZIP 获取完整源码。

版本 **1.1.8**。在手机 APP 或桌面客户端中手动开启 SSH，按需恢复保存的登录公钥和 NAS 主机密钥。即使设备没有之前的 SSH 开机修复服务，也可以使用。只授权给可信 NAS 管理账户：恢复 root 登录属于高权限操作。

本版修复固件更新后 root 登录目录丢失导致公钥恢复失败的问题，并在页脚显示实际运行的公共权限组件版本。恢复时识别固件的 `mi-shell`，通过 Dropbear 服务专用的只读挂载恢复新 SSH 会话的 Bash 命令执行；保留原厂二进制，不开启密码认证。界面不预置或展示示例个人密钥文件名。

## 功能

- 查看 SSH、开机检查、密钥与开机修复状态，以及不包含密钥内容的操作记录。
- 手动恢复 `dropbear.socket`；等待正在运行的小米开机检查结束后才允许操作。没有保存公钥时默认只开启 SSH，不调用密钥恢复或生成函数，不改动任何密钥文件。不修改 RPMB、root 密码或全局防火墙，不关闭现有 SSH 会话。
- “无公钥时生成登录密钥”默认关闭，保存开关不会立即生成；明确开启并点击恢复时，才生成新的 Ed25519 登录密钥并安装其公钥。通过受认证接口领取一次 ZIP 密钥包，包含通用命名的公钥和登录私钥，不包含 NAS 主机私钥。领取后立即删除 NAS 临时私钥；15 分钟过期后由公共组件每分钟清理，或下一次访问时清理。请使用可信连接并保存好下载文件；丢失私钥后不能从公钥反推或再次下载。
- 用户自己上传公钥，不预置登录密钥。支持 Ed25519、RSA（至少 2048 位）、ECDSA。
- 可从未加密的 OpenSSH Ed25519 私钥提取并校验公钥。仅在内存与 OpenSSL 的标准输入中处理，不落盘、不写日志；加密私钥与其他私钥格式请使用对应 `.pub` 文件。建议上传公钥，上传私钥必须使用可信 HTTPS 连接。
- 恢复公钥追加到 root 的 `authorized_keys`，不覆盖其他公钥。“移除保存的公钥”只清除恢复材料，不撤销已写入的登录公钥。
- 首次安装保存当前 NAS Dropbear 主机密钥的 root 专用副本。已有保存的公钥，或用户明确开启登录密钥生成时，主机密钥缺失才按恢复副本处理；副本也缺失才重新生成，客户端需重新核对指纹。客户端登录私钥不是 NAS 主机密钥。
- 可在插件内明确确认后安装／更新原来的开机 SSH 修复服务，复用新版 `install-ssh-autostart-fix.sh` 的有界 worker 代码：等待真实开机检查完成，最多等待 300 秒，间隔 5 秒有限复查 12 次。安装插件本身不修改此服务；服务仅在授权文件缺失时按安装时保存的副本恢复，不覆盖现有授权。

## 安装、卸载

```bash
bash manage.sh install --ip 192.168.31.100 --users u123456789
bash manage.sh install --users u123456789        # NAS 本机，以 root 运行
bash manage.sh install --all-users
bash manage.sh install --list-users
bash manage.sh install --dry-run
bash manage.sh uninstall --users u123456789
```

WSL / Linux 自动使用 root SSH 远程安装；NAS 本机直接执行。首次部署需要现有 root 访问，不能在插件尚未安装、设备已经没有任何 root 入口时远程凭空恢复权限。安装与升级保留当前密钥材料；不预置任何客户端公钥或私钥，不重启 NAS。

与 Docker Manager、定时任务共用 **公共权限组件 1.0.6 / API v1**。安装包带完整公共组件，可以单独安装；逐用户注册 `sshrecovery` 授权，sudo 只能调用固定模块，无任意命令执行或路径上传接口。不同插件使用同一个 NAS UID 时拥有该账户已授权能力的并集，不是互相隔离的权限沙箱。

卸载不关闭 SSH、不移除 root 已有登录公钥，也不删除用户在插件中明确安装的开机修复服务。其他插件仍需公共组件时保留组件。最后一个 SSH 恢复用户卸载后清除专属恢复材料；当前 root 登录能力不因此撤销。

## 数据位置与完整性

- `/home/<用户>/plugin/sshrecovery/`：INFO、控制脚本、src/tmp 链接，以及预留的 `etc/var` 运行目录。
- `/nas/pool*/<用户>/plugin/pluginsrc/sshrecovery/ui/`：静态界面与 CGI，参与系统摘要校验。
- `/nas/pool*/<用户>/plugin/plugintmp/sshrecovery/`：小米系统校验临时目录，不存密钥。
- `/data/.minas-privileged/sshrecovery/`：root 0700 专用运行数据；`keys/<用户>.pub` 为恢复公钥，`host/dropbear_rsa_host_key` 为 NAS 主机密钥恢复副本（0400），`events.json` 为操作记录。
- 公共 root 组件在 `/data/.minas-privileged/`，不放在普通用户可改写的 `/data/plugin` 上级目录下。
- 选择文件后通过 JSON 请求在内存中传输，上传的私钥不建立临时文件。用户主动生成的登录私钥临时保存在 root 专用 `sshrecovery/tmp/generated-<用户>/`，仅一次下载、15 分钟过期。任何密钥、日志、锁或操作状态都不放进 `src`；不在运行时自动刷新 INFO 摘要。密钥导入、生成、下载与恢复后源码摘要必须保持不变。
- 用户明确安装的开机修复文件：`/data/ssh-autostart-fix/restore-ssh.sh`、`/etc/cron.d/keep-ssh`、`/etc/systemd/system/minas.boot_check.service.d/90-keep-ssh.conf`。

备份恢复数据时仅由 root 保存到受保护的位置，主机密钥副本不能公开、提交 Git 或传给其他账户。源码安装包不包含任何密钥材料。设备固件升级若删除 sudo、插件注册或公共组件，需要重新部署；插件不能保证在所有固件策略下永久恢复 root 入口。

## 项目结构与测试

```text
manage.sh                 统一安装／卸载入口
payload/install.py        标准插件注册与权限模块安装
payload/common/           可独立安装的公共组件
payload/common/modules/sshrecovery/  受限 SSH 模块与开机 worker（唯一维护位置）
payload/ui/               客户端界面、CGI、主题与桥接
payload/scripts/control   不改变 SSH 的插件生命周期控制
tests/                    密钥、授权、恢复与源码摘要回归
```

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

源码树与仓库不存真实密钥、用户配置或部署日志。开机 worker 一致性和公共组件跨安装包一致性测试需要父目录内的对应原项目；单独下载仓库时会跳过这些跨项目检查。

## 1.1.0 的状态检查与固件兼容

“服务器身份密钥”会验证 Dropbear 是否能解析服务器密钥；它与 root 的登录授权是两个文件。新增“实际登录授权”，分别检查 root 主目录、`.ssh`、`authorized_keys`、安全权限和保存的公钥是否已安装。rootx 目录缺失时不会显示登录授权已就绪；“恢复公钥已保存”也不代表已经安装到登录目录。服务 socket 已开启，仍须通过客户端实际执行 `id` 验证最终可用性。

旧固件没有 mi-shell 时跳过 shell 映射；旧 `/root` 登录位置会迁移公钥授权到可写的 `/home/rootx`，保留密码及其他账户记录。新固件的 mi-shell 通过 Dropbear 服务专用挂载处理，保留原厂二进制，新连接生效。

安装/更新开机修复还会部署自包含的 `/data/ssh-autostart-fix/recover-ssh.py`，并保存当前登录授权到 `login-authorized-keys`。开机检查结束后，仅在实际授权文件缺失时补回；现有文件不会被旧副本覆盖。每次明确更新开机修复会刷新副本，撤销公钥后应同步更新；删除该副本可停止缺失文件恢复。仍使用 300 秒等待和 12 次有限复查，不是常驻服务。

## 提前下载离线应急包

点击“下载离线应急包”并保存到电脑。ZIP 包包含自包含修复程序、开机 worker、账户 manifest、可选登录公钥、使用说明及 SHA256SUMS；**不包含登录私钥或 NAS 主机私钥**。

保留 Portainer 管理入口。若将宿主机 `/` 绑定到容器 `/nas`，把应急包解压到 NAS 用户共享文件夹 `data/ssh-emergency` 后，在容器 root Console 执行：

```sh
chroot /nas /usr/bin/python3 /nas/pool0/u123456789/data/ssh-emergency/recover-ssh.py --local-recover --offline
```

替换账户及实际解压位置。若 `/` 绑定到 `/nas/home`，chroot 的目录改为 `/nas/home`；宿主机 `/home/rootx` 在容器中的位置则是 `/nas/home/home/rootx`。

离线模式先修复文件，再通过 root 专用的一次性宿主机 Cron 激活 systemd 配置与 SSH，执行后移除任务。`pending` 仅表示已排队，不代表 SSH 可用。查看最终结果：

```sh
cat /nas/data/ssh-autostart-fix/emergency-result.json
```

已有 NAS root 终端可运行同一程序并去掉 `--offline`，另有只读的 `--diagnose`。这些 CLI 不通过插件 sudo 授予普通用户。

此路径需要宿主机 Python 3.9+、systemd、正常运行的 Cron，以及现有容器管理权限。未来固件若移除所有管理入口或所需组件，不能保证远程恢复；没有预留隐藏账户、免认证端口或修改 RPMB。旧固件分支通过回归测试，当前 mi-shell 固件在实际设备验证；没有模拟真实固件升级或断电。

## 1.1.4 界面调整

状态概览在桌面窗口保持五项等宽排列，手机上登录授权独占整行；目录说明合并在卡片底部。开机修复说明统一字体、字号和行距，等待时限、复查策略和运行方式对齐展示。

## 获取源码

在 GitHub 仓库页面选择 **Code → Download ZIP**，解压后保留项目目录结构，按本页说明运行 `manage.sh`。也可从 **Tags** 页面选择指定版本源码。

## 文件位置与校验边界

普通用户可管理的运行状态、缓存保存在本插件主目录 `var/`，不写入参与原厂摘要校验的 `src`。root 执行代码、权限登记、任务调度数据库和 SSH 恢复材料保留在受 root 保护的系统位置；当前用户可替换 `/home/<用户>/plugin` 的父路径，因此不能将这些可信材料直接移入普通用户可改写的目录。公共权限组件为 1.0.6。

更新安装会保留原有插件启用状态；定时任务也保留原调度开关。运行数据不写入 `src`，安装更新同步更新 INFO 与用户注册条目，并用原厂 `plugin.sh verify` 复核。Docker 和控制中心预先建立可写 `var`，兼容原厂开机后 root:用户的目录权限布局。

## 弹窗边界修复（1.1.4）

确认框、选择器、详情和操作提示限制在插件窗口内；支持窗口缩小、缩放和长文本。运行数据仍位于独立数据目录，安装时更新原厂校验摘要。
