# 统一工具箱 · 全功能 BUG 审计与修复报告

日期：2026-09-18　范围：`unified/unified.py`（10,470 行，16 个类，8 个页签 + 5 个子模块）

## 一、审计方法

1. 分 4 段对全文件做只读静态审计（App 与基础设施 / 硬件与剪贴板 / 空间与软件管家与快速启动 / 其余模块）。
2. 拿到约 25 条疑似缺陷后**逐条回到源码复核**，能用实测的一律实测（临时脚本 + 真实文件系统 / 真实剪贴板 / 真实 WMI 查询），不靠"读起来像有问题"下结论。
3. 只修**验证成立**的；对证伪的和属设计取舍的，单独说明不改的理由。

**这一步的意义**：25 条里有 2 条经实测被推翻，若直接照单修改，会改坏本来正确的代码。

| 审计结论 | 实测结果 | 处理 |
|---|---|---|
| 「仅改大小写的重命名永不生效」 | **不成立**。`apply_rename` 是两阶段改名（先全改临时名再改终名），终名阶段原名已不存在，`os.path.exists(dst)` 不会误判；实测 `readme.md → README.md` 成功 | 不改 |
| 「空目录扫描会跟进 junction 导致超深遍历」 | **不复现**。实测 `os.walk(followlinks=False)` 在本机 Python 3.11 下不进入 `C:\Users\All Users`、`Default User`、`Documents and Settings` | 不改 |
| 「撤销能作用到错误目录」 | **成立且会造成真实误伤**（见 P0-1） | 已修 |

## 二、已修复（19 项）

### P0 · 数据安全

**1. 批量重命名「撤销」能改错目录的文件**（`FileModule._rename_dialog`）
`state["folder"]` 会被后续「预览」改写，而撤销记录 `record` 只存文件名。在 A 目录执行改名 → 把目录改成 B 并点「预览」→ 点「撤销」，就会在 **B 目录**里按 A 的文件名做重命名。
实测（两个临时目录，B 里放一个与改名结果同名的文件）：`B/RENAMED_a.txt` 被改成了 `B/a.txt`，而 A 里被改名的文件没动。
**修法**：`_apply` 时把执行目录一并存入 `state["record_folder"]`，`_undo` 只用它，撤销后把目录框同步回去。

### P1 · 功能整体失效 / 数据错误

**2. 系统还原点功能完全不可用**（`create_restore_point` / `list_restore_points`）
日志用 `Out-File -Encoding unicode`（UTF-16LE + BOM）写出，却按 `gbk` 读回。gbk 把 `0x00` 当**合法单字节**保留，于是每行变成 `\x00C\x00R\x00E\x00A\x00T\x00E\x00D\x00=`，`startswith("CREATED=")` / `("RP: ")` / `("COUNT=")` 全部不命中——**列表恒显示"没有任何还原点"，创建成功也恒报"未新建还原点"，且全程没有任何报错**。
**修法**：新增 `_read_elevated_log()` 按 BOM 自动判定编码（UTF-16LE/BE、UTF-8-SIG，无 BOM 退回 gbk）；另外日志文件不存在时 `_run_elevated_ps` 返回 `None`（= UAC 被取消），不再把"没执行"谎报成"命令已执行"。

**3. 还原点对话框连点两个按钮会崩溃**（`SpaceModule._restore_dialog`）
「列出」和「创建」共用一个 `queue.Queue()`。UAC 等待期间连点：`_poll` 会把「创建」的 `(ok, msg)` 当成「列出」的 `(pts, total)` 解包，随后 `for p in pts`（bool 不可迭代）抛 TypeError，轮询链直接断掉。
**修法**：两个操作各用各的队列，并加 `busy` 互斥。

**4. 磁盘 SMART 健康信息张冠李戴**（`_render_disks`）
`Get-PhysicalDisk` 是按**物理盘**给数据，而磁盘列表是按**卷/分区**，旧代码用 `health[idx]` 硬配下标。本机实测：1 块物理盘、2 个卷（C:、D:），D: 因此**完全没有健康行**；在双盘机器上，第二个卷会显示**另一块硬盘**的健康状态、容量和温度。
**修法**：查询里补 `Get-Partition` 取盘符，新增 `_health_for_mount()` 按盘符匹配；盘符信息整体拿不到时，只在「卷数 == 物理盘数」这种 1:1 情形才退回下标，其余一律不显示（遵循本项目"不编造数字"的既有原则）。实测 C:、D: 现已正确对上同一块 SSD。

**5. 结束进程只按 PID，可能杀掉无关进程**（`HardwareModule._kill_pid`）
端口/进程列表是快照，PID 会被系统回收。确认框里的进程名也来自同一份旧快照。
**修法**：动手前用 `_same_proc_name()` 核对当前进程名，不符即拒绝并提示刷新；同时拦下 `os.getpid()`（防止误杀工具箱自己）。

**6. 「退出时清空剪贴板历史」没有真正清空**（`ClipboardModule.shutdown`）
只清了内存列表和 JSON，**截图 PNG 仍留在 `~/.unified_toolbox_cache`**（缓存清理本身也只删 40 个之外的孤儿文件）。隐私承诺落空。
**修法**：新增模块级 `purge_clip_image_cache()`，只删本程序写入的 `clip_<hex>.png`、不跟随符号链接；退出清空与设置里的「清理图片缓存」按钮共用（后者也不再无差别清空整个目录）。

**7. 顶栏「开机时长」永远是空的**（`HardwareModule.build`）
`self.up_lbl` 建好、pack 好之后，全文件再无任何赋值——一个永久空白的标签。
**修法**：建好即填入 `开机 Xh Ym`。

### P2 · 行为错误 / 静默失效 / 泄漏

**8. 悬浮窗位置记忆每次重启丢失**（`load_settings`）
`float_geo` 被写入设置文件，但不在 `DEFAULT_SETTINGS` 白名单里，`load_settings` 按白名单过滤 → 重启即丢。用 AST 脚本比对了全部 SETTINGS 键，确认只漏这一个。
**修法**：登记进 `DEFAULT_SETTINGS`。

**9. 设置中心「取消」无法还原主题预览**（`show_settings`）
`_apply_theme_live` 会销毁并重建设置窗口，新窗口的 `saved_theme = THEME_NAME` 已经等于刚预览的主题，于是 `theme_var.get() != saved_theme` 恒为假，取消成了空操作（界面文案却承诺"取消还原原主题"）。
**修法**：把"打开设置时的主题"挂到 App 实例（`_settings_theme_at_open`）跨窗口保存；save/cancel 时清空；点 X 也绑成 cancel。（后来主题切换改为就地重着色、不再重建窗口，`cancel` 在还原主题后直接关窗；见第 20 条。）
实测：打开(blue) → 预览(purple) → 取消 → 确实回到 blue。

**10. 快速面板对图片条目粘贴的是字面文字**（`App._qp_paste`）
统一走 `clipboard_append(h["text"])`，而图片条目的 `text` 是占位符 `[图片] 800×600` → 目标程序粘到的是这串字。
**修法**：按 `id` 找回历史真身交给 `cm._copy_img()`（`_copy_img` 改为返回 bool 便于判断成败）。实测剪贴板里是 80×40 的真图，`uses` 使用计数也正确记到了正主（旧实现连计数都没记）。

**11. 硬件仪表定时器永不停止**（`HardwareModule._gauge_tick`）
`_gauge_tick` 无条件自我续排，`stop()` 只置 `_stop_flag` → 切走页签后仍有一条 30fps 空转定时器跑到退出，与项目"退出更干净/切页签就停"的目标不符。
**修法**：`stop()` 里 `after_cancel` 并复位 `_gauge_started`，`_gauge_tick` 检查 `_stop_flag` 不再续排（回来时由 `start()` 重启）。

**12. 剪贴板搜索每敲一键渲染两次**（`build()` + `start()` 各挂一条 trace）
`stop()` 只摘掉一条，另一条永远摘不掉（泄漏）。
**修法**：只在 `start()` 挂一次。

**13. 定时任务会因一个坏配置值静默死掉**（`_schedule_tick`）
设置文件是明文 JSON、用户可手改。`sch_clean_hours` 被改成 `null` 或字符串时，`int(SETTINGS.get(...))` 抛错；而这段代码在 `after` 回调里，一旦抛错就再也排不上队 → **30 秒定时器永久停摆，且打包成无控制台 exe 时完全无提示**。
**修法**：新增 `_as_int(value, default, lo, hi)`，替换全部 6 处 `int(SETTINGS.get(...))`。

**14. 设置里 Spinbox 清空后点「保存」会中断保存**
`int(sch1_h.get())` 在输入框为空时抛 TclError，`save()` 直接中断，用户看不到任何反馈。
**修法**：`_clamp_spin()` 兜底，非法值回退默认（168 / 45）。

**15. 极速搜索的排除名单形同虚设**（`build_file_index`）
两层问题：调用时**根本没传** `skip_prefixes`；而且传入的片段形如 `\Windows\WinSxS`，代码却拿它 `startswith` 整条绝对路径（`c:\windows\winsxs\...`），**永远匹配不上**。结果 WinSxS、Installer、node_modules、AppData 全部进索引，又慢又臃肿。
**修法**：新增 `_path_has_segments()` 按「连续目录名序列」匹配，调用点补上参数，跳过判断只在下钻时做一次。14 条正反用例验证：能跳过 WinSxS/node_modules/AppData\Local\Temp，且**不会**误伤 `D:\work\temp`、`my_temp`、`microsoft`、`AppData\Roaming`、`node_modules_like`。

**16. 目录树图状态栏把字节数当成项数**（`SpaceModule` 树图）
`scan_dir_sizes` 返回的 `total` 是**字节总和**，旧文案却是 `共 {total} 项合计 {_fmt(total)}` → 显示成"共 12345678 项合计 11.8 MB"。
**修法**：改为 `合计 X · 子项 N 个`。

**17. 查询中关窗会抛 TclError**（文件占用查询、目录树图的 `_poll`）
轮询循环缺少 `winfo_exists` 保护，关窗后仍对已销毁控件 `config`/`insert`。
**修法**：补 guard。（其余 14 处 poll 循环逐个检查过，本来就都有 guard。）

### P1 · 窗口每次只开"半屏"（用户报告）

**18. 最大化状态从不被记住**（`App._save_geometry` / `App.__init__`）
`_save_geometry` 在窗口最大化时**直接 return**，既不记录"用户想要最大化"，也不更新几何值；而全文件**没有任何一处**调用过 `state("zoomed")`。
结果：习惯最大化使用的用户，无论最大化多少次，每次启动都回到上一次的窗口态尺寸——在 1920×1080 上就是 1100×906 那一小块，观感就是"每次都只开半屏"。
**修法**：把最大化状态一并持久化（`maximized`），启动时如实复原；窗口态尺寸仍只在非最大化时更新，所以从最大化双击还原时依然落在一个正常大小上。另在设置中心「常规」加一个**「启动时最大化窗口」**勾选框（`start_maximized`），勾上即开始生效，取消勾则立即还原为窗口态。
实测：打包 exe 启动后窗口 1936×1048、`showCmd=3`（SW_SHOWMAXIMIZED）。

**19. 跑一次测试就会覆写用户真实设置文件**（`tests/integration_checks.py`）
这些检查会构造真实的 `App`，而 `_quit_app() → _save_geometry() → save_settings()` 会写到**真实的** `~/.unified_toolbox_settings.json`。只有个别检查覆盖了 `SETTINGS_FILE`，其余检查一路把用户的设置**重置成默认值**——本次就是它把用户的窗口尺寸从 `1100x906` 篡改成了 `1100x500`（500 是 `minsize` 下限）。
**修法**：新增 `isolate(module, folder)`，把全部 8 个用户级落盘路径（settings / history / 图片缓存 / 索引 / 片段库 / 清理日志 / 快速启动 / 配色）统一指向临时目录并重置 `SETTINGS`，所有构造 App 的检查一律先调用它。
实测：先往真实设置文件写入哨兵值，再跑整套检查 → 文件**逐字节未变**。

## 三、未修改但需要知情
- **审计日志写在删除之后**（`_log_clean` 在 `finally` 里以删除后统计写入）。正常流程记录完整，只有进程被硬杀才可能缺记录。要更严可改成"先写开始记录再删"，但会改动审计日志格式，故未动。
- **「空间清理 → 删除空文件夹」无审计日志、不受白名单约束**。但它有明确的二次确认、列出待删清单、走回收站（可还原）、且删除前会重新校验目录仍为空——属设计取舍。使用说明中"只处理白名单目录 + 每次清理写审计日志"的承诺是写给磁盘清理的。
- **五个子模块并非死代码**：`CleanupModule` / `UninstallModule` / `FileModule` / `ActivationModule` / `SetupModule` 虽不在 `MODULES` 列表里，但由 `SpaceModule`、`SoftwareModule`、`VerifyModule` 作为子模块实例化使用（我最初的判断有误，已在复核中纠正）。
- **已失效的旧测试**：`test_features.py` 里断言 `main()` 含 `ERROR_ALREADY_EXISTS`，但实现早已改为 `OpenMutexW` 探测——这是**本次改动之前就红**的陈旧断言，已改为断言真实机制。

## 四、验收

| 项目 | 结果 |
|---|---|
| `unittest discover -s tests` | **70 / 70 通过**（新增 `tests/test_regressions.py` 22 个用例） |
| `tests/integration_checks.py` | **6 / 6 通过**（含新增的窗口状态检查、弹窗布局检查） |
| 动态扫全部 8 个页签 + 4 套主题循环 + 设置开关 + 退出 | **0 个回调异常** |
| 设置对话框功能测试 | 预览→取消→主题确实回到原值；清空 Spinbox 保存→回退 168/45 |
| 快速面板 | 剪贴板实测为真图 DIB（80×40），文字条目正常 |
| 磁盘 SMART | 实测 C:/D: 正确对到同一块物理盘 |
| 窗口状态 | 打包 exe 启动即最大化（1936×1048，showCmd=3）；最大化→退出→再启动仍是最大化 |
| 测试隔离 | 往真实设置文件写哨兵后跑整套检查，文件逐字节未变 |
| `dist\统一工具箱.exe` | 已 `--clean` 全新建（构建前后源码 MD5 一致），启动正常 |

新增回归测试**专门把 P0 的误伤路径固化成断言**：`test_undo_record_is_names_only_so_callers_must_pin_the_folder` 用真实文件复现"撤销会被误用到别的目录"，防止回退。

## 五、后续补修

**20. 切换主题会中断任务并丢掉页面状态**（`App._apply_theme_live`）
旧实现是 `apply_theme → _setup_ttk_style → _switch(当前页)`：`_switch` 先 `stop()` 全部模块，再销毁、重建当前页。正在跑的扫描 / 安装 / 卸载会被掐断；搜索框（`UninstallModule`、`ClipboardModule` 的 `StringVar` 在 `build()` 里重新创建）、列表数据和滚动位置全部清零；设置窗口也要关掉重开，未保存的选项随之丢失。
**修法**：改为**就地重着色**——按"旧主题色值 → 新主题色值"递归改写现有控件（tk 选项 / Canvas 图元 / Treeview 标签 / Text 标签 / Listbox 项），再补顶部骨架、状态栏和主题预览块；不再调用 `_switch`，也不销毁设置窗口。只有重涂抛异常时才退回重建兜底；「取消」改为还原主题后直接关窗。
实测：`blue → purple → blue` 全程页面对象、搜索框内容和设置窗口保持不变，控件背景正确切到新主题色；集成检查 7/7 通过。

**21. 20+ 处手写 `queue + after` 轮询各写各的**（跨线程 UI 更新）
每处后台任务都复制一遍「`queue.Queue()` → worker 里 `put` → 主线程 `get_nowait` → `queue.Empty` 时 `after` 续排」。模板重复本身只是啰嗦，真正的风险是复制时漏掉守卫或停止条件：有的没检查窗口是否已销毁，有的 worker 抛异常后永远卡在「查询中…」，有的把两个操作塞进同一个队列导致 `(ok, msg)` 被当成 `(pts, total)` 解包。
**修法**：新增模块级 `run_in_background(widget, work, handle, interval=200, alive=None, on_error=None)`，把骨架收成一处：
- `work(report)` 在 daemon 线程跑，可多次 `report()` 进度 / 日志 / 最终结果；
- `handle(message)` 在主线程按序执行，返回 False 可提前停止；
- 完成标记与结果走**同一个 FIFO 队列**，杜绝「刚判空、worker 又放入结果」的丢消息竞态；
- 统一 `winfo_exists` / `alive()` 守卫，关窗、切页或扫描 token 被替换即停；
- worker 异常默认交 Tk `report_callback_exception`，与回调里直接抛异常一致，不会静默挂死。
共迁移 30 处后台任务调用（硬件报告、端口查询、OCR、清理/扫描、软件更新与安装、UWP、还原点、激活、驱动检查、检查更新等）。`HardwareModule._run_in_queue`、`UninstallModule._icon_q`、剪贴板采集、托盘事件等**常驻服务循环**按设计保留——它们是长期消费者，不是一次性任务。
**回归测试**：新增 `PollerTests` 6 项（顺序投递、自动停止、token 过期、窗口销毁、异常转交、提前停止），并加一条 AST 断言：除 `run_in_background` 外，任何函数都不得再同时出现 `queue.Queue()` 与 `get_nowait()`。
实测：101 项单元测试、7 项集成检查、`ruff` 与 `compileall` 全过。

**22. 6 套按钮工厂各抄一份、Treeview 排序各写一遍**
`BaseModule`、`CleanupModule`、`UninstallModule`、`FileModule`、`LaunchModule` 各有一个 `_mkbtn`，`HardwareModule` 还有一个从未被调用的 `_make_btn`。细节已经漂移：字号 9 / 10 混用、`pady` 3 / 4 混用，返回不返回按钮也不一致。排序同样复制了「取 `get_children` → `sort` → 逐行 `move`」，文件页和进程页各一份；改一处排序规则很容易漏掉另一处。
**修法**：新增模块级 `make_secondary_button(...)` 与 `sort_treeview(tree, column, key=None, reverse=False)`：
- 各模块的 `_mkbtn` 只保留自己的默认字号 / 颜色 / 边距，主体统一调用 `make_secondary_button`；`_mkbtn` 的返回值契约保持不变（`UninstallModule` 等依赖返回按钮的调用点不受影响）；
- 文件页按 `parse_size` 排「大小」，进程页按数值排 `CPU%` / `PID` / `内存`、其余按文本升序，全部走同一个 `sort_treeview`；行仍然用 `tree.move` 原地挪动，选中、tag 和滚动位置都不丢；
- 删除无调用点的 `HardwareModule._make_btn`。
- 卸载页的「名称 / 大小 / 安装时间…」排序是数据层重排后重建列表（`_sorted_apps`），不涉及逐行 `move`，保留原逻辑。
**回归测试**：新增 `WidgetFactoryTests` 6 项（按钮样式与悬停、文本/数值排序、文件大小单位、进程三列数值排序、两个 AST 去重断言）。
实测：107 项单元测试、7 项集成检查、`ruff` 与 `compileall` 全过。

**23. 主题配色是裸字典 + `globals()` 注入，字段拼错只能等运行时**
`THEMES` 用 `dict[str, dict]` 存 `label` / `dark` / 14 个颜色 / `STRIP`，`apply_theme` 用 `globals()[k] = t[k]` 写模块常量。颜色名拼错、缺字段、`STRIP` 不是二元组，都要等切主题时才暴露；自定义配色导入只检查 key 是否存在，不检查值类型。
**修法**：把每套配色改为不可变 `Palette` 数据类（`frozen=True, kw_only=True`）：
- 14 个颜色字段 + `label` / `dark` / `STRIP` 在构造时即校验，字段缺失或拼错直接 `TypeError`；
- `as_globals()` 只导出颜色别名，`apply_theme` 仍是唯一写入点；全文件 1.18 万行继续按 `CYAN/PANEL` 裸常量读取，避免上千处改成 `THEMES[...].X` 的大范围风险（这是刻意保留的兼容层，不是漏改）；
- 新增 `ACTIVE_PALETTE` 记录真正显示中的调色板；自定义配色文件被替换后再次应用时，旧色映射不会因为 `THEMES["custom"]` 已被覆盖而变成空映射；
- `as_dict()` / `from_mapping()` 负责自定义配色文件与导出 JSON 的往返；导入时校验缺字段、非字符串颜色，并把 JSON 里的 `STRIP` 列表规范回二元组，坏文件回退到 `CYAN/BORDER`；
- 设置中心、渐变条、预览块全部改为属性访问，不再按下标取字典。
**回归测试**：新增 `ThemePaletteTests` 5 项（四套内置配色完整且不可变、`apply_theme` 别名导出不污染调色板、未知主题回落 blue、自定义文件校验与 `STRIP` 归一化、连续替换自定义配色时 `ACTIVE_PALETTE` 仍指向真正显示的对象）；集成检查里连续替换两次自定义配色并断言页面实际换色。
实测：113 项单元测试、7 项集成检查、`ruff` 与 `compileall` 全过。

**打包验证**：本地按 `统一工具箱.spec` 用 PyInstaller 6.22.2 重新打包，`dist/统一工具箱.exe` 为 19.5 MB（CI 下限 10 MB），嵌入图标可正常提取；启动后主窗口标题为“统一工具箱 v3.10.6”，关闭并清理进程树后无残留。CI 的 `build` job 已在 tag `v3.10.6` 上跑通（static-checks、unit-tests、build 全绿，artifact `UnifiedToolbox-unsigned` 已上传）。

**发版验证**：v3.10.6 已发布到 GitHub 与 Gitee；发布后发现 Gitee 附件上传把 `.sha256` 也命名成 exe，已修正 `release.py` 并补回归测试，同时手工修复 v3.10.6 的 Gitee 附件（exe 19,495,526 字节 + `.sha256` 86 字节，下载哈希一致）。
