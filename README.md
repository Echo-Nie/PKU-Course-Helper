# 北大选课助手 · PKU Course Helper

**中文** | [English](README.en.md)

面向北京大学补退选阶段的 Windows 桌面辅助工具。使用北大红配色的单页工作台，在同一页面完成使用说明、运行状态查看、课程管理与账号设置。

> 本项目是基于 [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026) 的修改版本，延续了更早两代开源项目的工作，**并非从零原创，也不是北京大学官方软件**。感谢学长学姐们的积累与分享，详细致谢见文末。

![单页工作台（离线示例）](docs/images/workspace.png)

## 本次改进

- 移除侧边栏与多页切换：简短说明 → 运行情况 → 目标课程 → 账号与设置。
- 主修、选修、辅修三种界面分类；主修与选修都使用学校主修入口，原有后端调度不变。
- 支持班号 `00`；保存为数字 `0`，匹配时二者等价。
- 状态下方直接显示失败原因与处理建议，区分认证失败、选课入口不可用、指定页未找到课程、课程冲突等情况。
- 保留开始／停止、运行中保存与确认重启、按身份和页码调度、组内优先级与拖动排序、课程互斥、延迟选课、日志、INI 导入导出和运行期间的防睡眠功能。
- 清理旧 Docker 文件、训练代码、过期界面脚本与截图；保留 ONNX 模型、来源信息、许可证和离线测试样本。

## 使用打包后的程序

基础便携包适用于 **Windows 10/11 x64**，需要系统已有 **Microsoft Edge WebView2 Runtime** 和 **.NET Framework 4.6.2 或更高版本**。不需要安装 Python 或 Node.js。可自行按下文打包，也可在仓库 Actions 中运行 Windows portable 构建并下载产物；若 Releases 中提供成品，请下载完整 ZIP。

1. 将 ZIP **完整解压**到可写文件夹，例如 `D:\PKUCourseHelper`。
2. 退出旧版程序，双击 `PKUCourseHelper.exe`。必须保留同目录的 `_internal` 等文件，不能只复制 EXE。
3. 在页面下方填写统一认证学号和密码。桌面界面的密码仅在本次会话中保留，退出后需重新输入。
4. 添加目标课程：

   | 字段 | 填写说明 |
   | --- | --- |
   | 课程类别 | 主修／选修使用主修入口；辅修使用辅修入口。按你在学校系统中实际使用的入口填写。 |
   | 所在页码 | 该课程在对应身份的补退选计划中的页码，从 1 开始。 |
   | 课程名称、开课单位 | 与学校页面完整一致。 |
   | 班号 | 允许 `00`／`0`；这是班号，不是完整课程编号。 |
   | 延迟选课 | 可选：仅当剩余名额不高于设定阈值时尝试选课。 |

5. 按需调整同一入口、同一页内的优先级。互斥组内一门课确认选中后，其余课程停止尝试。
6. 保存配置，点击页面上方的“开始运行”；查看状态下方的原因说明，必要时展开详细日志。
7. 运行中修改并保存配置后，可确认“重启并应用”，或让修改在下次运行生效。关闭程序会停止任务。最终结果以学校的已选列表为准。

配置和日志在 EXE 同目录的 `data/` 中。迁移旧配置时，先退出两个程序，再复制旧 `data/` 到新 EXE 同目录。不要将 `data/`、账号、密码或日志提交到 GitHub，也不要放进分享的 ZIP 中。

### 如何理解失败提示

| 提示 | 含义与处理方式 |
| --- | --- |
| 账号错误／密码错误 | 仅在学校明确指出具体错误时分别显示；核对统一认证信息。 |
| 账号或密码错误 | 学校没有区分错误字段，程序不会猜测；先在学校网页核对登录。 |
| 辅修入口不可用 | 没有识别到辅修入口。普通选修请选“选修”；若网页可进入辅修，可能是入口识别兼容性问题。 |
| 主修／选修／辅修未找到课程 | 登录后在指定入口、指定页未匹配到课程；检查全名、班号、开课单位、页码及是否已加入补退选计划。 |
| 上课／考试冲突、学分限制等 | 按学校反馈处理，程序不会自动退掉已有课程。 |
| 访问受限或需同意选课协议 | 按提示处理后手动重新开始；不要通过提高请求频率反复重试。 |

建议保留默认查询间隔 `6 秒`、随机偏移 `0.2`。运行时保持网络可用、电脑唤醒；任何间隔都不能保证不触发学校限制，程序也不能保证选课成功。

## 从源码运行

准备 **Python 3.11 x64**、**Node.js 22**、系统 WebView2。以下命令可在 **Git Bash** 中执行：

```bash
git clone https://github.com/Echo-Nie/PKU-Course-Helper.git
cd PKU-Course-Helper
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
python desktop.py
```

上述依赖直接安装到当前 Python；虚拟环境不是运行的必需条件。也可以自行使用 Python 虚拟环境隔离依赖。**运行完整程序的入口是 `desktop.py`**。

前端改动后重新执行 `npm --prefix frontend run build` 并重启程序；仅修改 Python 时重启程序即可。源码修改不会自动更新以前打包的 EXE。

### 仅预览界面

构建前端后，在项目根目录运行 `python desktop.py --preview` 可打开离线桌面预览；打包后也可运行 `./PKUCourseHelper.exe --preview`。预览使用独立的临时示例配置，不会登录或选课，也不读取你的日常配置。

开发前端时可使用浏览器预览：

```bash
cd frontend
npm ci
npm run dev
```

打开终端显示的本地地址并加 `/?preview=1`，通常是 `http://127.0.0.1:5173/?preview=1`。这是模拟数据，不会登录或选课；刷新页面会重置预览数据。加上 `&scenario=errors` 可查看错误提示示例。按 `Ctrl+C` 停止预览服务。

## 打包为 EXE

在项目根目录执行。**Git Bash：**

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./tools/build_local.ps1
```

**PowerShell：**

```powershell
.\tools\build_local.ps1
```

脚本会检查 Python 3.11 x64，自动在项目内创建 `.venv-build-tools` 和 `.venv-desktop`，安装锁定依赖，构建前端，运行测试，生成 EXE，再执行离线自检和包内容检查。这些环境仅用于构建，不要求成品使用者安装虚拟环境。

成功后终端会输出路径：

```text
dist/portable/<本次构建编号>/PKUCourseHelper-windows-x64-portable.zip
build/portable-<本次构建编号>/dist/PKUCourseHelper/PKUCourseHelper.exe
```

ZIP 可复制到其他符合运行条件的 Windows 电脑，完整解压后运行。基础包使用系统 WebView2；如需内置私有 WebView2 的发行包，请见 [发布说明](docs/RELEASING.md)。离线自检不会访问学校，也不代表真实选课必然成功。

## 项目结构

```text
desktop.py             桌面程序入口
frontend/              React 单页界面
autoelective/desktop/   配置、调度、状态反馈、Windows 平台适配
autoelective/           沿用的学校接口、解析及兼容代码
resources/model/       ONNX 模型、来源记录与模型许可证
tests/                 离线回归测试与验证码测试样本
packaging/             Windows 打包与发行流程
tools/build_local.ps1  本地一键打包入口
```

`data/`、构建缓存、虚拟环境和成品目录均不纳入 Git。上游协议与仍被测试使用的兼容代码保留，避免影响现有功能。

## 参考项目与致谢

本项目在以下项目基础上修改，保留上游 MIT 许可证与来源说明；此仓库从当前修改版本初始化：

1. [Aerisun/PKUAutoElective2026](https://github.com/Aerisun/PKUAutoElective2026)：本项目的**直接基础**，提供 Windows 桌面程序、ONNX 推理、多身份多页面调度等实现。
2. [Hovennnnn/PKUAutoElective2023](https://github.com/Hovennnnn/PKUAutoElective2023)：前代适配工作及 CNN + GRU + CTC 验证码识别模型。
3. [zhongxinghong/PKUAutoElective](https://github.com/zhongxinghong/PKUAutoElective)：最初的选课流程、学校接口、互斥与延迟规则等基础能力。

感谢各位学长学姐和所有贡献者。此分支主要调整单页交互、界面样式、分类展示、错误反馈和使用文档，不将上游成果宣称为原创。模型来源与许可见 [resources/model](resources/model/README.md)，项目许可见 [LICENSE](LICENSE)。
