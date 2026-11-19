# 飞智 BS2 Pro 游戏自动调档

游戏运行时自动选择硬件 **3 档**，所有游戏退出 **10 秒**后自动回到 **2 档**。多个游戏同时运行，只要还有一个在运行就保持 3 档；切到桌面也保持 3 档。

## 直接使用

需要 Windows 10/11、已在 Windows 蓝牙设置中配对的飞智 BS2 Pro，以及 Python。推荐 Python 3.10–3.12；本项目也在 Python 3.8 上完成实机验证。项目直接通过蓝牙 HID 通信，不需要安装飞智空间站。

下载或克隆仓库后，在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

如果 `python` 不在 PATH 中，可指定解释器：

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1 -Python "C:\Path\To\Python\python.exe"
```

安装脚本将依赖放入项目 `.deps`，把本机启动路径存入不受 Git 跟踪的 `.pythonw-path`。随后双击 **`start.vbs`** 打开控制窗口，自动调档随程序启动。

1. 散热器通电，并在 Windows 蓝牙设置里配对 BS2 Pro。
2. 打开工具。状态显示“无游戏运行 → 2 档”表示设备已确认。
3. 启动时自动搜索本机游戏，并内置 CS2/CSGO、三角洲的常见进程识别。启动游戏后，窗口会显示游戏名称及设备确认的 3 档。
4. 退出最后一个游戏，检测到退出 10 秒后回到 2 档（进程轮询另有最多约 2 秒延迟）。

**点击 × 会收到右下角系统托盘，自动控制继续运行。** 点击任务栏右侧的 `^`，找到蓝色风扇图标，单击即可打开窗口；右键可打开、暂停/恢复调档或退出。桌面快捷方式再次双击也会打开已有窗口。

托盘、任务栏、窗口标题栏使用相同的蓝色风扇图标。如创建桌面快捷方式，目标选择 `start.vbs`，图标可选择 `assets\fan.ico`。Windows 可能把新图标放进 `^` 的折叠区域，可以将图标拖到任务栏右下角常驻显示。

要完全关闭请点窗口或托盘菜单中的“退出程序”。退出工具时，若无游戏会尝试回到 2 档；有游戏运行时保留当前档位。托盘启动失败时会保留或恢复窗口，避免无法找回程序。

勾选“登录 Windows 后自动运行”即可随登录收到托盘；取消勾选即可移除。此项默认关闭。配置写入当前用户 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下的 `BS2ProGameGear`，不需要管理员权限。

## 自动搜索与添加游戏

- 每次启动自动扫描一次，也可以点“自动搜索游戏”。
- 读取 Steam 多库记录、Epic 清单、GOG / EA（Origin）/ Ubisoft 的常见注册表安装记录；同时解析桌面与开始菜单快捷方式。
- 检查所有本地固定磁盘的浅层目录和 Program Files、WeGameApps 等目录，通过 Unity、Unreal、Godot 等引擎特征识别独立游戏；可添加其他搜索目录。
- 根据实际游戏主程序评分选择检测目标，过滤更新器、崩溃处理器、反作弊和通用启动器。
- 不把已知的 Steam 壁纸、Blender、运行库等软件作为游戏导入。
- 游戏装在其他位置时，点“添加搜索目录”；无法自动判断时，点“添加游戏 .exe”。
- 请选择实际游戏进程，例如三角洲的 `DeltaForceClient-Win64-Shipping.exe`，而不是 WeGame 启动器。
- 双击列表中的项目可以启用/停用检测。重新搜索会保留手动添加项和启停选择。
- 自动识别无法覆盖全部游戏平台或所有启动器结构，新增游戏后请检查列表。

例如洛克王国和三角洲都有名为 `startup_runner.exe` 的启动器；自动搜索会分别找到各自的实际游戏程序。洛克王国检测 `NRC-Win64-Shipping.exe`，因此关闭游戏后即使启动器留在后台也会降档。

## 删除检测程序

选中列表中的项目，点击“删除所选检测程序”，或按 **Delete**，也可右键删除。支持按 Ctrl 多选后一起删除。

删除只移除本工具的检测规则，**保留实际程序文件**，保存后立即更新监测。删除记录写入 `config.json` 的 `excluded_games`，重启或重新搜索不会自动加回来；扫描期间删除也有效。

误删时点击“恢复已排除项”。再次通过“添加游戏 .exe”手动加入同一程序，也会解除对应的排除。

## 手动测试

窗口中的“散热器自身的启停设置”可直接读取和设置 BS2 Pro，不需要飞智空间站：

- **关闭**：不随蓝牙连接状态自动启停。
- **即时（推荐）**：蓝牙连接即启动，断开即停转。
- **延时约 1 分钟**：蓝牙断开后继续运行约一分钟再停转。
- **通电自启**：散热器重新接通电源时启动，与 Windows 登录自启动是两个独立设置。

选择后点击“应用到散热器”。工具先等待设备 ACK，再通过设备状态通知读回确认；只有确认后才保存为已生效。设置保持在散热器内，重连时只读取，不反复写入。点“读取设备设置”可查看设备当前值。

电脑关机后的联动依赖蓝牙实际断开；“关闭本工具窗口”只隐藏到托盘，不会关闭系统蓝牙。散热器需正常供电，Windows 蓝牙配对需保留。实际断电/关机联动需要在下次正常开关机时验证。

“测试 3 档”和“测试 2 档”会暂停自动调档，等待设备 ACK 并读回确认；测试完点“恢复自动调档”。如果有多个自动调速软件同时运行，建议关闭飞智空间站的智能调速。固定档切换不会修改原来的档位转速、灯光或固件。

蓝牙掉线后每 5 秒重试；设备读回档位每 15 秒校验一次。连续检测到 3 次外部改档会暂停并提示，避免持续争抢。进程读取失败时保留当前档位。

## 文件与命令

- `config.json`：游戏列表、额外搜索目录、`exit_delay_seconds`（0–300 秒）。修改后重新打开工具。
- `status.json`：GUI 实例最近的设备确认状态。
- `radiator.log`：换档、连接和错误记录，自动限制日志大小。
- `error.log`：启动失败的详细原因。

```powershell
python main.py --devices       # 枚举本型号设备，不改档
python main.py --status        # 查询设备档位
python main.py --gear 3        # 切到 3 档并读回确认
python main.py --gear 2        # 切到 2 档并读回确认
python main.py --scan          # 搜索并保存游戏列表
python main.py --watch         # 命令行监测，Ctrl+C 退出
python -m unittest discover -s tests -v
```

工具只允许运行一个控制实例；运行命令行控制或诊断前，先退出图形工具。`--watch` 的状态保存为 `config.status.json`。

移到其他电脑或更换 Python 后，重新运行 `setup.ps1` 更新本机启动路径；登录自启动如已开启，应在工具中取消并重新勾选以更新路径。卸载时先取消登录自动运行并退出工具，再删除项目目录。

## 开发与验证

```powershell
python -m unittest discover -s tests -v
python tests\gui_check.py
```

自动测试不连接散热器；窗口自检使用临时配置和模拟设备。以下为手动实机测试，运行前退出图形工具：

```powershell
python tests\hardware_check.py
python tests\settings_hardware_check.py
python tests\tray_check.py
```

`hardware_check.py` 使用临时进程验证 2→3→2 档切换；`settings_hardware_check.py` 会临时修改设备启停设置，最后恢复原值；`tray_check.py` 注册并移除临时托盘图标。

仓库不包含本机 `config.json`、日志、设备地址、依赖目录或 Python 路径。首次启动会创建本机配置，示例见 `config.example.json`。自动识别无法覆盖所有游戏；目前只验证 BS2 Pro，其他型号不作为兼容性承诺。

GitHub 调研、协议来源和实测记录见 [docs/RESEARCH.md](docs/RESEARCH.md)。
