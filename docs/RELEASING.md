# 发布免安装版

当前只发布 Windows 11 x64 免安装 ZIP。工作流位于
`.github/workflows/windows-release.yml`；不会生成安装器或修改用户系统设置。

## 发布

1. 提交并推送完整源码、锁文件、测试和构建脚本，不要提交账号、密码、日志或本地数据。
2. 在 GitHub 的 **Releases → Draft a new release** 创建版本，例如 `v0.1.3`。
3. 点击 **Publish release**。工作流随后自动构建并检查用户包。
4. 构建成功后，Release 会出现：
   - `PKUCourseHelper-Windows11-x64-portable.zip`
   - `SHA256SUMS.txt`

GitHub 自动生成的 `Source code` ZIP/TAR 是源码，不是普通用户成品。也可以在
**Actions → Release Windows portable → Run workflow** 手动试打包；手动运行只生成
Actions artifact，不修改 Release。

## 用户包边界

ZIP 内只有一个 `PKUCourseHelper/` 目录，包含主程序、私有 WebView2、
Python 运行依赖、模型、许可证、运行方式标记和一份用户说明。不得包含：

- 源码、测试或构建工具；
- 构建审计报告；
- 账号、密码、课程配置；
- `data`、日志、缓存或浏览器用户目录；
- 安装器或卸载器。

程序首次运行后才在自身目录创建 `data`。用户停止任务并退出后，删除整个目录即可
移除软件自有内容。

## 自动检查

发布工作流会执行前端与 Python 测试、PyInstaller 冻结、离线自检、包内容白名单、
模型与运行组件完整性检查，并核对私有 WebView2 的版本、来源和微软签名。只有检查通过
的 ZIP 和校验文件会成为 Release 附件；详细报告只保留在 Actions artifact 中。

自动检查不会登录学校，也不能替代真实界面、真实网络和长时间运行验收。主程序目前
没有商业代码签名，Windows 可能提示未知发布者。

## 发布约束

- 正式标签应指向本次交付的完整提交。
- 已公开版本不应使用不同内容覆盖；发生修改时发布新版本。
- 签名或重新打包后文件内容会变化，必须重新生成校验文件。
- 更新私有 WebView2 时，同时更新 `packaging/release-inputs.json` 中的版本、下载地址和
  SHA-256，并重新完成验收。
