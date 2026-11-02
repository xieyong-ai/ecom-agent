"""启动器：解决"streamlit run 起不来"的三类环境问题。

为什么需要它（都是实际踩到的坑）：
    1. 机器上可能装了多个 Streamlit。PATH 上的 `streamlit` 命令指向的可能是
       另一套 Python（本项目实测：PATH 上是 1.32，项目依赖装在 1.66），
       用错解释器会出现各种莫名报错或页面空白。
    2. Windows 允许两个进程重复绑定同一端口（SO_REUSEADDR）。上一次没退干净的
       Streamlit 仍占着 8501 时，新进程不会报错，浏览器却连到那个半死的实例，
       表现就是"一直转圈 / 起不来"。
    3. 在错误的目录执行 `streamlit run app.py`，只会得到一句冷冰冰的
       "File does not exist: app.py"。

本脚本做三件事：选对解释器 → 确认端口真的可用 → 用绝对路径启动 app.py。

用法：
    python tools/launch.py              # 默认 8501，被占用时自动换端口
    python tools/launch.py --port 8510
    python tools/launch.py --restart    # 先结束占着端口的旧 Streamlit 再启动（重启）
    python tools/launch.py --stop       # 只停服务，不启动（相当于 stop.bat）
    python tools/launch.py --status     # 只查状态：开没开、在哪个端口（相当于 status.bat）
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_STREAMLIT = (1, 40)


def _streamlit_version(py: str) -> tuple[int, ...] | None:
    """探测某个解释器里的 streamlit 版本；不可用返回 None。"""
    try:
        out = subprocess.run(
            [py, "-c", "import streamlit,sys;print(streamlit.__version__)"],
            capture_output=True, text=True, errors="replace", timeout=25,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    m = re.match(r"(\d+)\.(\d+)", out.stdout.strip())
    return tuple(int(x) for x in m.groups()) if m else None


def _candidates() -> list[str]:
    """按优先级列出可能的解释器。"""
    cands: list[str] = []
    if os.getenv("ECOM_PYTHON"):
        cands.append(os.environ["ECOM_PYTHON"])
    for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
        p = ROOT / rel
        if p.exists():
            cands.append(str(p))
    # 本项目依赖实际安装的位置（WorkBuddy 自带 Python），存在则优先于 PATH
    for base in (Path.home() / ".workbuddy", Path("D:/bigdata/.workbuddy")):
        versions = base / "binaries" / "python" / "versions"
        if versions.is_dir():
            cands += [str(p) for p in sorted(versions.glob("*/python.exe"), reverse=True)]
    cands += [sys.executable, "python", "python3", "py"]
    seen, uniq = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def pick_interpreter() -> str:
    """选一个装了足够新 Streamlit 的解释器；都不满足就原样返回 sys.executable。"""
    for py in _candidates():
        ver = _streamlit_version(py)
        if ver and ver >= MIN_STREAMLIT:
            return py
    return sys.executable


def port_owner(port: int) -> int | None:
    """返回监听该端口的 PID（Windows / POSIX 都走 netstat 兜底）。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, errors="replace", timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        # 必须匹配 ":8501 " 而不是 ":8501"——否则 85010 也会被当成 8501
        if re.search(rf":{port}\s", line) and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
    return None


def can_bind(port: int) -> bool:
    """端口是否真的空闲（没有任何进程在监听）。

    这里不用 bind 探测：Windows 会对处于 TIME_WAIT 的端口直接报占用，
    上一次启动刚结束就会误判成"被占用"。改为两步确认：
    ① netstat 里有没有 LISTENING 的属主；② 实际能不能连上。
    连接失败且没有属主，才认为端口空闲。
    """
    if port_owner(port) is not None:
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) != 0


def health_ok(port: int) -> bool:
    """占用端口的 Streamlit 是否真的活着。

    区分两种"端口被占"：一种是上次没关的窗口（健康检查 200，属于正常使用），
    另一种是进程还没退干净（连不上，浏览器会一直转圈）。两者的处理完全不同，
    所以要先问一句 /health 再下结论。
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def describe_pid(pid: int) -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
            capture_output=True, timeout=20,
        )
        # PowerShell 重定向输出的编码随版本而变：pwsh 7 默认 UTF-8，Windows PowerShell
        # 用系统 ANSI 代码页（简体中文为 cp936）。先按 UTF-8 严格解码，失败再退回 mbcs，
        # 否则中文路径会变成「璇惧鎷撳睍」这种乱码。
        try:
            cmd = out.stdout.decode("utf-8").strip()
        except UnicodeDecodeError:
            try:
                cmd = out.stdout.decode("mbcs", errors="replace").strip()
            except LookupError:
                cmd = out.stdout.decode("utf-8", errors="replace").strip()
        return cmd[:120] if cmd else "(无法读取命令行)"
    except (OSError, subprocess.SubprocessError):
        return "(无法读取命令行)"


def stop_service(port: int) -> int:
    """停掉监听在指定端口上的本项目 Streamlit。

    为什么需要单独一个"关"的入口：Ctrl+C 在 Streamlit 上经常看起来生效了
    （终端回到提示符、页面也刷不出来了），但进程还挂在后台占着端口——
    Windows 又允许重复绑定，于是下次启动"成功"却连到那个半死的旧实例。
    这个函数做完事会**确认端口真的释放**，而不是发完 taskkill 就说成功。
    """
    pid = port_owner(port)
    if pid is None:
        print(f"端口 {port} 上没有进程在监听——服务已经是停的。")
        print("如果之前换过端口，用 python tools/launch.py --stop --port 8502 指定。")
        return 0

    owner = describe_pid(pid)
    print(f"发现进程 PID={pid}: {owner}")
    # 双保险：命令行里带 streamlit，或者 /health 有响应，都认为是我们自己的服务
    if "streamlit" not in owner.lower() and not health_ok(port):
        print("这不是本项目的 Streamlit 进程，为避免误杀不做处理。")
        print(f"确认后请手动执行: taskkill /PID {pid} /F")
        return 2

    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    for _ in range(25):
        if can_bind(port):
            break
        time.sleep(0.2)

    if can_bind(port):
        print(f"已停止（PID={pid}），端口 {port} 已释放。")
        return 0
    print(f"进程已结束，但端口 {port} 仍被占用（可能处于 TIME_WAIT 或被子进程继承）。")
    print("等几秒再试；仍不行就重启终端。")
    return 1


def report_status(port: int, span: int = 10) -> int:
    """只报告状态，不改动任何进程。

    为什么需要它：遇到「页面打不开」时，真实原因通常只有三种——服务压根没开、
    开在别的端口上（启动器发现 8501 被占会自动 +1）、进程还在但已经连不上。
    这三种的处理方式完全不同，先看清是哪一种，比反复重启有效。
    """
    print("[服务状态]")
    hits: list[tuple[int, int, bool]] = []
    for p in range(port, port + span):
        pid = port_owner(p)
        if pid is not None:
            hits.append((p, pid, health_ok(p)))

    if not hits:
        print(f"  端口 {port}-{port + span - 1}：都没有进程在监听")
        print()
        print("  结论：服务是停的。双击 start.bat 启动即可。")
        return 1

    for p, pid, alive in hits:
        state = "正常响应" if alive else "无响应（进程还在，但连不上）"
        print(f"  端口 {p}：PID={pid}，{state}")

    live = [p for p, _, alive in hits if alive]
    print()
    if len(live) > 1:
        # 之前的启动器在端口被占时会自动 +1，配合「忘了关旧窗口」很容易叠出多个实例。
        # 它们各自跑一份代码，你改完代码在哪一个上生效完全取决于打开了哪个地址。
        print(f"  检测到 {len(live)} 个实例同时在跑：{', '.join('http://localhost:%d' % p for p in live)}")
        print("  它们各自跑一份代码，容易改完代码却看不到效果。")
        print("  建议：双击 stop.bat 逐个关掉，再只双击一次 start.bat。")
        print()
    if live:
        target = live[0]
        if target != port:
            print(f"  注意：服务开在 {target}，不是默认的 {port}（上次 {port} 被占用，自动换了端口）。")
        print(f"  打开地址：http://localhost:{target}")
        if not health_ok(target):
            print("  提示：页面打不开就先刷新；仍不行用 stop.bat 关掉再 start.bat 重开。")
        return 0

    print("  进程在，但健康检查没通过——这正是「浏览器一直转圈」的原因。")
    print("  处理：双击 stop.bat 关掉，再双击 start.bat。")
    return 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("ECOM_PORT", "8501")))
    ap.add_argument("--stop", action="store_true", help="只停止占用端口的服务，不启动")
    ap.add_argument("--status", action="store_true", help="只报告状态，不改动任何进程")
    ap.add_argument("--kill-stale", "--restart", dest="kill_stale", action="store_true",
                    help="先结束占用端口的旧 Streamlit 再启动（相当于重启）")
    ap.add_argument("--headless", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    # 子进程的日志会直接写到同一个 stdout，本脚本的提示必须行缓冲才不会被甩到最后
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    if args.stop:
        return stop_service(args.port)
    if args.status:
        return report_status(args.port)

    py = pick_interpreter()
    ver = _streamlit_version(py)
    print(f"[1/3] 解释器: {py}")
    print(f"      streamlit: {'.'.join(map(str, ver)) if ver else '未安装'}")
    if not ver:
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
        print("      ! 该解释器没有 streamlit", file=sys.stderr)
        if venv_py.exists():
            print("      项目内已存在 .venv，但里面没装依赖。执行：", file=sys.stderr)
            print(f"        \"{venv_py}\" -m pip install -r requirements-lock.txt", file=sys.stderr)
        else:
            print("      建议先建项目内独立环境（宿主 Python 被替换时依赖会一起消失）：", file=sys.stderr)
            print("        python -m venv --copies .venv", file=sys.stderr)
            print(f"        \"{venv_py}\" -m pip install -r requirements-lock.txt", file=sys.stderr)
        return 1
    if ver < MIN_STREAMLIT:
        print(f"      ! 版本低于 {'.'.join(map(str, MIN_STREAMLIT))}，可能不支持本项目用法", file=sys.stderr)

    port = args.port
    print(f"[2/3] 检查端口 {port}")
    if not can_bind(port):
        pid = port_owner(port)
        owner = describe_pid(pid) if pid else "(未知进程)"
        alive = health_ok(port)
        # 命令行读不到时（权限/编码问题），能通过 /health 也说明是本项目的 Streamlit
        is_streamlit = "streamlit" in owner.lower() or alive
        print(f"      端口被占用，PID={pid}: {owner}")
        if is_streamlit and args.kill_stale and pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
            # taskkill 是异步的，端口要等一下才真正释放
            for _ in range(15):
                if can_bind(port):
                    break
                time.sleep(0.2)
            print(f"      已结束旧 Streamlit 进程 {pid}")
        elif is_streamlit and alive:
            print(f"      {port} 上已经有一个在跑的实例（多半是你上次没关的那个窗口）。")
            print(f"      想直接用它：浏览器打开 http://localhost:{port} 即可；")
            print("      想换成本次代码：关掉旧窗口后再双击一次，或用 --restart 让本脚本替你重启。")
        elif is_streamlit:
            print("      这是上次没退干净的 Streamlit（进程还在，但已经连不上了）——")
            print("      它会让浏览器连到死实例，表现为「一直转圈 / 起不来」。")
            print(f"      可执行: python tools/launch.py --restart   或手动 taskkill /PID {pid} /F")
        if not can_bind(port):
            for alt in range(port + 1, port + 20):
                if can_bind(alt):
                    print(f"      改用空闲端口 {alt}")
                    port = alt
                    break
            else:
                print("      ! 找不到可用端口", file=sys.stderr)
                return 1

    cmd = [
        py, "-m", "streamlit", "run", str(ROOT / "app.py"),
        "--server.port", str(port),
        "--server.headless", "true" if args.headless else "false",
        "--browser.gatherUsageStats", "false",
    ]
    print(f"[3/3] 启动: http://localhost:{port}")
    print("      按 Ctrl+C 停止。改动 core/ 后需要重启本服务（Streamlit 不会重载被 import 的模块）。\n")
    try:
        return subprocess.call(cmd, cwd=str(ROOT))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
