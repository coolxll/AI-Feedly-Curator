# Checkpoint

## Current status
- Overall: `arena-app` Tauri 桌面化已完成基础构建与数据集读取接入，Windows 安装包已生成。
- Progress: Tauri 原生构建链路已打通，前端已接入真实数据集读取，应用可正常启动并显示 benchmark 数据。
- Key outcomes: 创建图标资源、配置 Tauri bundle、实现 `list_datasets` 和 `get_dataset` Rust commands、前端调用 Tauri API 展示数据。

## What changed
- Completed:
  - 创建 `arena-app/src-tauri/icons/` 目录及图标文件 (`icon.png`, `icon.ico`)
  - 更新 `tauri.conf.json` 配置图标路径
  - 安装 `@tauri-apps/api` 依赖
  - 实现 Rust commands: `list_datasets`, `get_dataset`
  - 更新前端 `App.tsx` 调用 Tauri commands 并展示数据集列表与详情
  - 成功构建 MSI 和 NSIS 安装包
- In progress: Python evaluator bridge 设计与实现
- De-scoped / canceled: None

## Blockers / risks
- Blockers: None (构建链路已通)
- Risks: 1) 数据集路径在开发/生产环境可能不同，需进一步测试；2) Python evaluator bridge 尚未实现；3) Runs 和 Compare 页面仍为 placeholder 数据。
- Mitigations: 1) 已在 Rust 中实现路径检测逻辑，优先查找项目根目录；2) 下一步设计 Python 调用协议。

## Next steps
- [ ] 设计 Tauri command 到 Python evaluator 的调用协议 — 本周
- [ ] 实现 Runs 页面：读取 `arena/scoring/runs/` 目录的回测结果
- [ ] 实现 Compare 页面：多 run 对比视图
- [ ] 决定是否加入 GitHub Actions 的 Tauri Windows 构建工作流 — USER

## Notes / links
- 当前分支: `feature/arena-tauri-app`
- 构建输出: `src-tauri/target/release/bundle/msi/Scoring Arena_0.1.0_x64_en-US.msi`, `src-tauri/target/release/bundle/nsis/Scoring Arena_0.1.0_x64-setup.exe`
- 关键代码: [arena-app/src/App.tsx](arena-app/src/App.tsx), [arena-app/src-tauri/src/main.rs](arena-app/src-tauri/src/main.rs)
- 数据集: `arena/scoring/datasets/`