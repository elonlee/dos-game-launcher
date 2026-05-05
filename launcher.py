#!/usr/bin/env python3
"""
DOS Game Launcher - Curses-based TUI for selecting and launching DOS games.
Supports multi-column display, exe editing, shell mode, and favorites.
"""

import curses
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
CONF_DIR = BASE_DIR / "conf"
TEMPLATE_CONF = BASE_DIR / "dosbox-x.conf"
GAMES_DIR = BASE_DIR / "games"

# Color pair IDs
COLOR_STAR = 1


def load_games():
    mapping = db.get_mapping()
    games = []
    for name, info in mapping.items():
        if info.get("error"):
            continue
        games.append({
            "name": name,
            "dir": info.get("dir", ""),
            "exe": info.get("exe"),
            "config": info.get("config"),
            "favorite": info.get("favorite", False),
        })
    games.sort(key=lambda g: g["name"])
    return games


def save_mapping(games):
    db.update_mapping_entries(games)


def generate_config(game_dir_name: str, exe_path: str, conf_path: Path) -> None:
    """Generate a minimal game-specific dosbox-x config with only [autoexec]."""
    content = f"""[autoexec]
# Auto-generated for {game_dir_name}
mount c {GAMES_DIR}
c:
cd {game_dir_name}
call {exe_path}
exit
"""
    conf_path.write_text(content, encoding="utf-8")


def generate_shell_config(game_dir_name: str) -> Path:
    """Generate a temporary config that opens a shell in the game directory."""
    content = f"""[autoexec]
# Shell mode for {game_dir_name}
mount c {GAMES_DIR}
c:
cd {game_dir_name}
"""
    fd, tmp_path = tempfile.mkstemp(suffix=".conf", prefix="dos_shell_")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return Path(tmp_path)


def launch_game(game, shell_mode=False):
    cmd = ["dosbox-x"]
    if TEMPLATE_CONF.exists():
        cmd += ["-conf", str(TEMPLATE_CONF)]
    if shell_mode:
        tmp_conf = generate_shell_config(game["dir"])
        if not tmp_conf:
            return
        cmd += ["-conf", str(tmp_conf)]
    else:
        config_path = BASE_DIR / game["config"]
        if not config_path.exists():
            return
        cmd += ["-conf", str(config_path)]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def edit_exe(stdscr, game):
    """Inline editor for the game's executable. Handles backspace, delete, arrows."""
    height, width = stdscr.getmaxyx()
    prompt = ""
    buf = list(game.get("exe") or "")
    cursor = len(buf)
    start_x = 0
    row = height - 1

    curses.curs_set(1)
    while True:
        # draw current buffer directly
        visible = "".join(buf)[:width - 1]
        stdscr.addstr(row, 0, " " * (width - 1))
        stdscr.addstr(row, 0, visible)
        stdscr.move(row, min(cursor, width - 1))
        stdscr.refresh()

        key = stdscr.getch()

        if key in (curses.KEY_ENTER, 10, 13):
            new_exe = "".join(buf).strip()
            game["exe"] = new_exe
            conf_path = CONF_DIR / f"{game['name']}.conf"
            generate_config(game["dir"], new_exe, conf_path)
            curses.curs_set(0)
            return True
        elif key == 27:  # ESC cancel
            curses.curs_set(0)
            return False
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            if cursor > 0:
                cursor -= 1
                buf.pop(cursor)
        elif key == curses.KEY_DC:
            if cursor < len(buf):
                buf.pop(cursor)
        elif key == curses.KEY_LEFT:
            if cursor > 0:
                cursor -= 1
        elif key == curses.KEY_RIGHT:
            if cursor < len(buf):
                cursor += 1
        elif key == curses.KEY_HOME:
            cursor = 0
        elif key == curses.KEY_END:
            cursor = len(buf)
        elif 32 <= key <= 126:
            if len(buf) < (width - 1) * 2:
                buf.insert(cursor, chr(key))
                cursor += 1
        # ignore other keys


def draw_menu(stdscr, games, selected_idx, scroll_top, max_rows, cols, col_width, filter_mode):
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Title with filter indicator
    if filter_mode == "favorite":
        title = " DOS 游戏启动器 [收藏] "
    else:
        title = " DOS 游戏启动器 [全部] "
    try:
        stdscr.addstr(0, (width - len(title)) // 2, title, curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * (width - 1))
    except curses.error:
        pass

    # Game list
    total_rows = math.ceil(len(games) / cols)
    for row in range(max_rows):
        actual_row = scroll_top + row
        if actual_row >= total_rows:
            break
        y = 3 + row
        for c in range(cols):
            idx = actual_row * cols + c
            if idx >= len(games):
                break
            game = games[idx]
            x = c * col_width + 1
            marker = "▶" if idx == selected_idx else " "
            name = game["name"]

            # Build display string
            prefix_parts = []
            if game["favorite"]:
                prefix_parts.append("★")
            prefix_parts.append(marker)
            prefix = " ".join(prefix_parts)
            if prefix:
                prefix += " "

            avail = col_width - 3
            display = f"{prefix}{name}"
            if len(display) > avail:
                display = display[:avail - 1] + "…"
            else:
                display = display.ljust(avail)

            attr = curses.A_REVERSE if idx == selected_idx else curses.A_NORMAL
            try:
                # If favorite and not selected, draw star in red
                if game["favorite"] and idx != selected_idx:
                    # Find the star position
                    star_pos = display.find("★")
                    if star_pos >= 0:
                        before = display[:star_pos]
                        after = display[star_pos + 1:]
                        stdscr.addstr(y, x, before, attr)
                        stdscr.addstr(y, x + len(before), "★", curses.color_pair(COLOR_STAR) | curses.A_BOLD)
                        stdscr.addstr(y, x + len(before) + 1, after, attr)
                    else:
                        stdscr.addstr(y, x, display, attr)
                else:
                    stdscr.addstr(y, x, display, attr)
            except curses.error:
                pass

    # Footer
    footer_left = " ↑↓←→/hjkl 移动 | Enter 启动 | Tab 切换视图 | 空格 收藏 | e 修改程序 | c 进入目录 | q 退出 "
    footer_right = f" 共 {len(games)} 个游戏 "
    try:
        stdscr.addstr(height - 2, 0, "─" * (width - 1))
        stdscr.addstr(height - 1, 0, footer_left[:width - 1])
        if width > len(footer_right) + len(footer_left):
            stdscr.addstr(height - 1, width - len(footer_right) - 1, footer_right)
    except curses.error:
        pass

    stdscr.refresh()


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(False)
    stdscr.keypad(True)

    # Initialize colors
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        try:
            curses.init_pair(COLOR_STAR, curses.COLOR_RED, -1)
        except curses.error:
            # fallback if terminal doesn't support default background
            curses.init_pair(COLOR_STAR, curses.COLOR_RED, curses.COLOR_BLACK)

    try:
        db.init_db()
        all_games = load_games()
    except Exception:
        stdscr.clear()
        stdscr.addstr(0, 0, "Database not initialized. Please run setup_games.py first.")
        stdscr.refresh()
        stdscr.getch()
        return

    if not all_games:
        stdscr.clear()
        stdscr.addstr(0, 0, "No games found in mapping.")
        stdscr.refresh()
        stdscr.getch()
        return

    filter_mode = "all"  # "all" or "favorite"
    selected_idx = 0
    scroll_top = 0

    def get_filtered_games():
        if filter_mode == "favorite":
            return [g for g in all_games if g["favorite"]]
        return all_games

    while True:
        games = get_filtered_games()
        if not games:
            # If filter results in empty list, switch back to all
            filter_mode = "all"
            games = get_filtered_games()

        height, width = stdscr.getmaxyx()
        cols = min(3, max(1, (width - 2) // 24))
        col_width = (width - 2) // cols
        max_rows = max(1, height - 5)
        total_rows = math.ceil(len(games) / cols)

        # Clamp selection
        selected_idx = max(0, min(selected_idx, len(games) - 1))

        # Ensure scroll_top keeps selected item visible
        selected_row = selected_idx // cols
        if selected_row < scroll_top:
            scroll_top = selected_row
        elif selected_row >= scroll_top + max_rows:
            scroll_top = selected_row - max_rows + 1
        scroll_top = max(0, min(scroll_top, total_rows - max_rows))

        draw_menu(stdscr, games, selected_idx, scroll_top, max_rows, cols, col_width, filter_mode)
        key = stdscr.getch()

        if key == curses.KEY_UP or key == ord('k'):
            new_idx = selected_idx - cols
            if new_idx >= 0:
                selected_idx = new_idx
        elif key == curses.KEY_DOWN or key == ord('j'):
            new_idx = selected_idx + cols
            if new_idx < len(games):
                selected_idx = new_idx
        elif key == curses.KEY_LEFT or key == ord('h'):
            if selected_idx % cols > 0:
                selected_idx -= 1
        elif key == curses.KEY_RIGHT or key == ord('l'):
            if selected_idx % cols < cols - 1 and selected_idx + 1 < len(games):
                selected_idx += 1
        elif key == curses.KEY_PPAGE:
            selected_idx = max(0, selected_idx - cols * max_rows)
            scroll_top = max(0, scroll_top - max_rows)
        elif key == curses.KEY_NPAGE:
            selected_idx = min(len(games) - 1, selected_idx + cols * max_rows)
            if selected_row >= scroll_top + max_rows:
                scroll_top = min(total_rows - max_rows, selected_row)
        elif key == ord('\n') or key == curses.KEY_ENTER:
            game = games[selected_idx]
            if game["config"]:
                launch_game(game)
            else:
                stdscr.clear()
                stdscr.addstr(0, 0, f"No config for: {game['name']}")
                stdscr.refresh()
                stdscr.getch()
        elif key == ord('\t'):
            # Tab switches filter mode
            filter_mode = "favorite" if filter_mode == "all" else "all"
            selected_idx = 0
            scroll_top = 0
        elif key == ord(' '):
            game = games[selected_idx]
            game["favorite"] = not game["favorite"]
            save_mapping(all_games)
            # If in favorite mode and we just unfavorited, we need to adjust
            if filter_mode == "favorite" and not game["favorite"]:
                # Recalculate filtered list
                new_games = get_filtered_games()
                if selected_idx >= len(new_games):
                    selected_idx = max(0, len(new_games) - 1)
        elif key == ord('e'):
            game = games[selected_idx]
            if edit_exe(stdscr, game):
                save_mapping(all_games)
        elif key == ord('c'):
            game = games[selected_idx]
            launch_game(game, shell_mode=True)
        elif key == ord('q') or key == 27:  # q or ESC
            break


if __name__ == "__main__":
    curses.wrapper(main)
