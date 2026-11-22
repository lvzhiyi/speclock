# SpecLock (workflow-core 0.23.1) — 兼容 Cursor 无绑定目录会话与空/相对执行目录

- **兼容 Cursor 无绑定目录会话**：`cursor_gate.choose_root` 忽略空字符串 `""` 并接受 `workspace_roots` 为空或 `None`；`normalize` / `handle` 在未绑定任何工作区目录且未提供显式目录时直接旁路放行，避免误用 hook 进程当前目录或报 `ENGINE_CURSOR_FORMAT_ERROR`。
- **兼容单根下 `Shell` 相对 `working_directory`**：当存在唯一工作区根或 `CURSOR_PROJECT_DIR` 时，按该基准目录解析 `Shell` 的相对 `working_directory` 并继续校验工作区边界；多根歧义、越界目录与非空相对 `CURSOR_PROJECT_DIR` 仍严格拒绝。
- **回归测试补强**：在 `test_cursor_gate.py` 新增 `test_unbound_session_and_empty_or_relative_directories`，覆盖无绑定目录会话、空路径、单根相对目录与多根拒绝边界。
