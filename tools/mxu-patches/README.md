# MXU 本地补丁

`mxu-v2.5.2-instance-callback-routing.patch` 修复多实例同时运行时，MaaFramework
回调被写入当前活动标签页而导致日志串页的问题。

`mxu-v2.5.2-scheduler-pending-preempt.patch` 修复定时点遇到实例忙碌时直接丢弃
策略的问题。定时策略会进入持久化待执行队列并保留 20 分钟；短任务完成后立即
补跑，长时间的 `zhuogui_hundui` 会通过 MXU 统一停止接口安全停止后补跑。
同一实例的同一时间槽只会入队一次，避免窗口恢复或轮询造成重复执行。

补丁基于 MXU `v2.5.2`（提交
`71b00db6f1fb1f258c1a3278b1c6ab3f34991e67`）。它为控制器、资源、任务器和上下文
回调附加 `instance_id`，并让前端按该 ID 写入对应实例的日志。

重新构建：

```powershell
git clone --branch v2.5.2 https://github.com/MistEO/MXU.git mxu-build
Set-Location mxu-build
git apply ..\my_mhxy\tools\mxu-patches\mxu-v2.5.2-instance-callback-routing.patch
git apply ..\my_mhxy\tools\mxu-patches\mxu-v2.5.2-scheduler-pending-preempt.patch
pnpm install --frozen-lockfile
pnpm build
pnpm tauri build --no-bundle
```

构建产物位于 `src-tauri\target\release\mxu.exe`。发布到运行目录时将其重命名为
`Maa_MHXY_MG.exe`。

补丁会为发布构建启用 Tauri 的 `custom-protocol`。不要直接运行未启用该特性的
`cargo build --release`，否则程序会加载 `tauri.conf.json` 中的 Vite 开发地址
`http://localhost:1420`，并显示 `ERR_CONNECTION_REFUSED`。
