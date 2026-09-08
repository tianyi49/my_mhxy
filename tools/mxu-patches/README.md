# MXU 本地补丁

`mxu-v2.5.2-instance-callback-routing.patch` 修复多实例同时运行时，MaaFramework
回调被写入当前活动标签页而导致日志串页的问题。

补丁基于 MXU `v2.5.2`（提交
`71b00db6f1fb1f258c1a3278b1c6ab3f34991e67`）。它为控制器、资源、任务器和上下文
回调附加 `instance_id`，并让前端按该 ID 写入对应实例的日志。

重新构建：

```powershell
git clone --branch v2.5.2 https://github.com/MistEO/MXU.git mxu-build
Set-Location mxu-build
git apply ..\my_mhxy\tools\mxu-patches\mxu-v2.5.2-instance-callback-routing.patch
pnpm install --frozen-lockfile
pnpm build
cargo build --release --manifest-path src-tauri\Cargo.toml
```

构建产物位于 `src-tauri\target\release\mxu.exe`。发布到运行目录时将其重命名为
`Maa_MHXY_MG.exe`。
