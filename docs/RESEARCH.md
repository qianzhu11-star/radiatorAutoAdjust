# 协议参考与实现说明

本项目是面向 Windows、飞智 BS2 Pro 的独立实现，直接通过蓝牙 HID 控制设备，不加载飞智空间站的程序、DLL 或服务。参考公开协议与游戏库扫描设计，未整体复制或执行下列上游项目。

## 参考项目

- [TIANLI0/THRM](https://github.com/TIANLI0/THRM)：BS 系列设备识别、控制命令、ACK 确认和设备设置。
- [nzlov/flydigictl](https://github.com/nzlov/flydigictl)：BS2 Pro 控制与状态通知位域解析。
- [Vasysik/flydigi-rework](https://github.com/Vasysik/flydigi-rework)：飞智散热器协议研究。不同型号的模式枚举存在差异，本项目使用 BS2 Pro 定义并读取实机状态验证。
- [trezor/cython-hidapi](https://github.com/trezor/cython-hidapi)：Python HIDAPI 绑定。
- [Sam-GG/PlayniteAutoImport](https://github.com/Sam-GG/PlayniteAutoImport/blob/main/src/Scanner.ps1)：安装目录去重、引擎特征、主程序评分与扫描排除设计。
- [johnray/WindowsGameExport](https://github.com/johnray/WindowsGameExport)：多平台安装记录与独立游戏目录扫描结合的结构。本项目只读取本机安装信息，不联网提交游戏库。
- [Playnite GOG 插件](https://github.com/JosefNemec/PlayniteExtensions/blob/master/source/Libraries/GogLibrary/GogLibrary.cs)：安装路径与 `goggame-*.info` 主启动任务的关联。
- [pystray 官方说明](https://pystray.readthedocs.io/en/latest/usage.html)：Windows 托盘消息循环、默认动作和菜单。

## BS2 Pro 通信

- HID VID `0x37D7`、PID `0x1002`；仅打开这个型号的接口。
- 报告 ID `02`，短控制报告为 23 字节。协议帧头为 `5A A5`。
- 长度字段为 `2 + payload 长度`，校验为命令、长度、载荷之和的低 8 位。
- `08 [1..4]` 选择硬件固定档；本工具限制为 2、3 档。
- `25` 查询工作状态：BS2 Pro 返回 1..4 为固定档，5 为实时模式。
- `24` 退出实时模式。
- 换档必须收到 ACK，并再次查询确认实际档位；写入成功不直接视为设备已换档。

固定档由设备自己维持，不需要温度监控驱动或持续推送 RPM。本项目不修改各档转速表、固件或灯光配置。

## 设备启停设置

- `0D [0/1/2]`：关闭、即时、延时智能启停。
- `0C [1/2]`：开启、关闭通电自启。
- `EF` 状态通知载荷第 2 字节：bit 1 为通电自启，bits 2..3 为智能启停枚举，bit 0 为实时调速模式。

两个设置必须分别解码，例如 `06` 表示“通电自启开启＋即时启停”。不能把 bit 1 混入智能启停枚举。

设置会写入设备存储；本项目先读取当前值，跳过相同设置，连续设置写入至少间隔 250 毫秒。应用后等待设备状态读回确认，再保存本地已确认值；重连只读取，不反复写入。

智能启停跟随蓝牙连接状态，不等同于退出软件。通电自启跟随重新供电，不等同于 Windows 登录自启动。实际关机、断电与蓝牙断连行为需要在目标机器上确认。

## 游戏发现与检测

扫描 Steam 多游戏库、Epic 清单、GOG/EA（Origin）/Ubisoft 常见注册表记录、桌面/开始菜单快捷方式，以及固定磁盘的浅层目录。目录扫描有深度和文件数量限制，在后台线程运行。

主程序选择优先 Unreal Shipping、Unity 同名 Data 目录、Godot PCK 等特征，过滤启动器、崩溃处理器、直播组件、共享运行库和反作弊程序。快捷方式只读目标路径，不执行、不读取登录参数。不同来源按完整路径去重。

检测只读取进程名称和可执行文件路径，不注入游戏进程。多个游戏并存时，最后一个游戏退出后才开始降档延迟。删除规则以 ID 和完整路径保存排除，避免重新扫描复活；不会删除目标 EXE。

## 托盘与窗口

托盘在独立 Windows 消息线程运行，回调通过队列交给 Tk 主线程。点 × 仅在托盘就绪时隐藏窗口；托盘失效则恢复窗口。再次启动通过 Windows 自动复位事件通知原实例显示窗口。

窗口、任务栏、托盘使用 `assets/fan.ico`；任务栏设置独立 AppUserModelID。图标包含 16/24/32/48/64 像素尺寸。

## 验证范围

- 自动测试覆盖协议校验、坏帧、设备读回失败、多游戏与延迟、扫描来源、删除持久化、实例恢复事件，以及设备设置独立位域解析。
- 窗口自检覆盖读取/应用设置、未确认不保存、错误提示、托盘隐藏/恢复、删除与恢复规则、图标加载和控件边界。
- 实机验证固定档 2→3→2，并用临时测试进程验证自动切换流程。
- 实机验证启停设置写入、ACK、状态读回、关闭并重开 HID 句柄后保持，最后恢复原值。
- 原生托盘测试通过 `Shell_NotifyIconGetRect` 验证注册，并测试打开、暂停/恢复和退出回调。

自动测试不要求连接硬件。实机测试需手动运行；没有自动关机、断电或关闭系统蓝牙的测试步骤。
