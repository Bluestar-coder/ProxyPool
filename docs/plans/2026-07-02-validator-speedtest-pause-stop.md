# 代理验证与测速暂停/停止控制 Implementation Plan

Created: 2026-07-02
Author: liu892981282@gmail.com
Agent: Claude Code
Status: VERIFIED
Approved: No
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** 为代理验证（ValidatorThread）和代理测速（SpeedTestThread）增加三态控制（运行中 / 已暂停 / 已停止），按钮内联在操作栏，两者独立控制，用户可随时暂停、恢复或终止任何一项操作。

## Approach

**Chosen:** 在 `AsyncWorkerThread.run()` 中创建 `asyncio.Event`，ValidatorThread / SpeedTestThread 的内层任务在获取 semaphore 前 `await self._pause_event.wait()`，主线程通过 `loop.call_soon_threadsafe` 操作事件；UI 按钮内联在操作栏，按运行状态动态显示/隐藏。

**Why:** asyncio.Event 天然与事件循环线程安全，零引入新依赖。暂停发生在任务间隙（已在飞行的并发槽位完成后才等待），不会破坏进行中的网络连接；stop() 取消 main_task 仍然有效。

## Context for Implementer

`AsyncWorkerThread.run()` 在 QThread 内部创建 event loop。`asyncio.Event` **必须在 `run()` 内部**（事件循环创建之后）实例化，不能在 `__init__` 中创建，因为 `asyncio.Event` 在 Python 3.10+ 不绑定 loop 参数，但其内部锁依赖运行中的事件循环。主线程调用 `pause()`/`resume()` 时通过 `loop.call_soon_threadsafe` 修改事件，跨线程安全。

## Runtime Environment

- **Start:** `uv run python main.py`
- **Port:** N/A（纯 UI 功能）
- **Verify:** 启动应用 → 代理验证 → 观察按钮变化 → 暂停 → 继续 → 停止

## Progress Tracking

- [x] Task 1: AsyncWorkerThread — 新增 pause/resume 支持
- [x] Task 2: ValidatorThread + SpeedTestThread — 接入暂停检查点
- [x] Task 3: UI 操作栏 — 内联暂停/停止按钮

## Implementation Tasks

---

### Task 1: AsyncWorkerThread — 新增 pause/resume 支持

**Objective:** 在 `AsyncWorkerThread` 的 `run()` 方法中初始化 `asyncio.Event`（默认 set，即"可运行"），新增 `pause()`、`resume()` 方法，通过 `loop.call_soon_threadsafe` 跨线程安全地清除/设置事件。新增测试覆盖暂停阻塞、继续解阻两种行为。

**Files:**

- Modify: `app/core/worker_thread.py`
- Create: `tests/test_worker_thread.py`

**Key Decisions / Notes:**

- `self._pause_event` 在 `run()` 中 `asyncio.new_event_loop()` 之后、`create_task()` 之前创建：`self._pause_event = asyncio.Event(); self._pause_event.set()`
- `pause()` / `resume()` 先检查 `hasattr(self, '_pause_event') and hasattr(self, 'loop') and not self.loop.is_closed()` 再操作，防止线程未启动时调用
- 现有 `stop()` 方法不变
- `is_paused` property：`return hasattr(self, '_pause_event') and not self._pause_event.is_set()`

**Definition of Done:**

- [ ] `AsyncWorkerThread.pause()` 调用后新任务在 `await self._pause_event.wait()` 阻塞
- [ ] `AsyncWorkerThread.resume()` 调用后阻塞任务立即继续
- [ ] 现有 `stop()` / `run()` 行为不变
- [ ] Verify: `uv run pytest tests/test_worker_thread.py -q`

---

### Task 2: ValidatorThread + SpeedTestThread — 接入暂停检查点

**Objective:** 在 `ValidatorThread._validate()` 和 `SpeedTestThread._test()` 内层函数的 `async with semaphore:` 之前插入 `await self._pause_event.wait()`，使暂停在任务间隙生效。

**Files:**

- Modify: `app/core/validator.py` (line 219 — `_validate` 内层函数)
- Modify: `app/core/speed_test.py` (line 87 — `_test` 内层函数)

**Key Decisions / Notes:**

- 修改位置：`_validate`（validator.py:221）`async with semaphore:` 前一行；`_test`（speed_test.py:89）`async with semaphore:` 前一行
- `Trivial:` 各自 ≤2 净增行，无新分支/符号/错误路径；覆盖：`tests/test_worker_thread.py` 中的 pause 行为测试（Task 1 已覆盖机制）+ 现有 `uv run pytest tests/test_validator.py tests/test_speed_test.py -q` 通过

**Definition of Done:**

- [ ] 暂停后发起验证/测速，已占用 semaphore 的并发槽位完成，新槽位不获取直至 resume()
- [ ] Verify: `uv run pytest tests/test_validator.py tests/test_speed_test.py -q`

---

### Task 3: UI 操作栏 — 内联暂停/停止按钮

**Objective:** 重构 `_build_action_bar()` 以保存"代理验证"和"速度测试"按钮引用，并在其后各添加一对隐藏的"暂停"+"停止"按钮；新增 `_set_validator_state(state)` / `_set_speed_state(state)` 状态机方法，在运行/暂停/空闲三态之间切换按钮的文本、可见性和启用状态；在启动、完成、暂停、停止各回调中调用对应状态机。

**Files:**

- Modify: `app/ui/main_window.py`

**Key Decisions / Notes:**

- 新增实例属性（在 `_build_action_bar()` 中赋值，不改 `__init__`）：`self._btn_validate`、`self._btn_validate_pause`、`self._btn_validate_stop`、`self._btn_speed`、`self._btn_speed_pause`、`self._btn_speed_stop`
- 状态机 `_set_validator_state(state: str)`，state ∈ {"idle", "running", "paused"}：
  - idle → validate 按钮 enabled，pause/stop 按钮 hidden
  - running → validate 禁用，pause 文本"暂停验证" visible，stop visible
  - paused → validate 禁用，pause 文本"继续验证" visible，stop visible
- `_on_validate_pause()`: 若 `is_paused` → resume() + state("running")；否则 pause() + state("paused")
- `_on_validate_stop()`: stop() + state("idle")
- 速度测试同理，方法名 `_on_speed_pause` / `_on_speed_stop`
- `_on_validation_finished()` 末尾加 `self._set_validator_state("idle")`
- `_on_speed_finished()` 末尾加 `self._set_speed_state("idle")`
- `_start_validation()` 成功启动后加 `self._set_validator_state("running")`
- `_start_speed_test()` 成功启动后加 `self._set_speed_state("running")`
- 不为 UI 新增测试（无可观测的纯 UI 行为单元测试），通过 E2E 手动验证

**Definition of Done:**

- [ ] 点击"代理验证"后，"代理验证"按钮禁用，"暂停验证"和"停止验证"按钮出现
- [ ] 点击"暂停验证"后，按钮文本变为"继续验证"，再次点击恢复为"暂停验证"且验证继续
- [ ] 点击"停止验证"后，验证中止，所有按钮恢复初始状态
- [ ] 速度测试按钮组行为与上述一致，与验证控制互不影响
- [ ] 验证或测速正常完成（未手动停止）后，按钮组恢复初始状态
- [ ] Verify: `uv run pytest -q` 全套通过（无 UI 回归）
