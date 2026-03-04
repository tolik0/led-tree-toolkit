import argparse
import curses

from animations import ANIMATION_DESCRIPTIONS, ANIMATIONS, run_animation


def parse_args():
    parser = argparse.ArgumentParser(description="Run LED animations.")
    parser.add_argument("name", nargs="?", choices=sorted(ANIMATIONS.keys()), help="Animation name")
    return parser.parse_args()


def pick_animation():
    items_3d = [
        name for name, anim_cls in sorted(ANIMATIONS.items()) if getattr(anim_cls, "is_3d", False)
    ]
    items_2d = [
        name
        for name, anim_cls in sorted(ANIMATIONS.items())
        if not getattr(anim_cls, "is_3d", False)
    ]
    items = [("3D", items_3d), ("2D", items_2d)]

    def ui(stdscr):
        curses.curs_set(0)
        idx_group = 0
        idx_item = 0

        while True:
            stdscr.clear()
            max_x = max(0, curses.COLS - 1)
            max_y = curses.LINES - 1

            def safe_addstr(row, col, text):
                if row >= max_y:
                    return
                stdscr.addstr(row, col, text[:max_x])

            y = 0
            safe_addstr(y, 0, "Select animation (arrows, Enter to run, q to quit)")
            y += 2
            for g_idx, (label, names) in enumerate(items):
                safe_addstr(y, 0, f"{label} animations:")
                y += 1
                for i, name in enumerate(names):
                    if y >= max_y:
                        break
                    prefix = "-> " if (g_idx == idx_group and i == idx_item) else "   "
                    desc = ANIMATION_DESCRIPTIONS.get(name, "")
                    line = f"{prefix}{name} - {desc}"
                    safe_addstr(y, 0, line)
                    y += 1
                y += 1
            stdscr.refresh()

            key = stdscr.getch()
            if key in (ord("q"), ord("Q")):
                return None
            if key in (curses.KEY_UP, ord("k")):
                idx_item = max(0, idx_item - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                idx_item = min(len(items[idx_group][1]) - 1, idx_item + 1)
            elif key in (curses.KEY_LEFT, ord("h")):
                idx_group = max(0, idx_group - 1)
                idx_item = min(idx_item, len(items[idx_group][1]) - 1)
            elif key in (curses.KEY_RIGHT, ord("l")):
                idx_group = min(len(items) - 1, idx_group + 1)
                idx_item = min(idx_item, len(items[idx_group][1]) - 1)
            elif key in (curses.KEY_ENTER, 10, 13):
                return items[idx_group][1][idx_item]

    try:
        return curses.wrapper(ui)
    except curses.error:
        return None


def main():
    args = parse_args()
    if args.name:
        run_animation(args.name)
        return
    choice = pick_animation()
    if choice:
        run_animation(choice)
        return
    print("Terminal too small for arrow UI. Enter animation name from the list above.")
    choice = input("Animation name: ").strip()
    if choice not in ANIMATIONS:
        raise SystemExit(f"Unknown animation: {choice}")
    run_animation(choice)


if __name__ == "__main__":
    main()
