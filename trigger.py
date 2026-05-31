#!/usr/bin/env python3
"""训练解题条件反射的命令行程序——集成 SM-2 艾宾浩斯记忆算法与 DeepSeek API 动态出题。"""

import os
import time
from typing import Optional

from logic import (
    sm2_update,
    load_data,
    save_data,
    generate_question,
    extract_subject,
    get_subjects,
)


# ============================================================
#  界面工具
# ============================================================

def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def wait_enter(prompt: str = "按回车键继续...") -> None:
    input(prompt)


# ============================================================
#  主菜单
# ============================================================

def menu() -> str:
    clear_screen()
    print("=" * 40)
    print("       解题条件反射训练器")
    print("       (SM-2 + DeepSeek 动态出题)")
    print("=" * 40)
    print()
    entries = load_data()
    now = int(time.time())
    due_count = sum(1 for e in entries if e.get("next_review", now) <= now)
    print(f"  当前题库数量: {len(entries)}")
    print(f"  待复习题目: {due_count}")
    print()
    print("  [1] 录入题目")
    print("  [2] 开始测试 (仅复习到期题目)")
    print("  [3] 查看题库")
    print("  [4] 删除题目")
    print("  [5] 重置复习进度")
    print("  [6] 退出")
    print()
    return input("  请选择 (1-6): ").strip()


# ============================================================
#  录入题目
# ============================================================

def add_entry() -> None:
    clear_screen()
    print("=" * 40)
    print("       录入新题目")
    print("=" * 40)
    print()
    keyword = input("  触发关键词: ").strip()
    if not keyword:
        print("\n  关键词不能为空。")
        wait_enter()
        return

    print()
    print("  请输入解题方法（输入空行结束）:")
    print("  " + "-" * 36)
    lines = []
    while True:
        line = input()
        if line == "" and lines and lines[-1] == "":
            break
        lines.append(line)

    solution = "\n".join(lines).strip()
    if not solution:
        print("\n  解题方法不能为空。")
        wait_enter()
        return

    data = load_data()
    for entry in data:
        if entry["keyword"] == keyword:
            print(f"\n  关键词「{keyword}」已存在，是否覆盖? (y/n): ", end="")
            if input().strip().lower() != "y":
                wait_enter("  已取消。按回车键返回...")
                return
            entry["solution"] = solution
            save_data(data)
            print(f"\n  已更新「{keyword}」。")
            wait_enter()
            return

    now = int(time.time())
    data.append({
        "keyword": keyword,
        "solution": solution,
        "next_review": now,
        "interval": 0,
        "ef": 2.5,
    })
    save_data(data)
    print(f"\n  已添加「{keyword}」。")
    wait_enter()


# ============================================================
#  查看题库
# ============================================================

def view_entries() -> None:
    clear_screen()
    print("=" * 40)
    print("       题库列表")
    print("=" * 40)
    print()
    data = load_data()
    if not data:
        print("  题库为空。")
        wait_enter()
        return

    now = int(time.time())
    # 按 next_review 升序排列（最急需复习的在前）
    data.sort(key=lambda e: e.get("next_review", now))

    for i, entry in enumerate(data, 1):
        kw = entry["keyword"]
        nxt = entry.get("next_review", now)
        interval = entry.get("interval", 0)
        ef = entry.get("ef", 2.5)
        due = "\U0001f534" if nxt <= now else "\U0001f7e2"
        if nxt <= now:
            status = "待复习"
        else:
            remaining = nxt - now
            days = remaining // 86400
            hours = (remaining % 86400) // 3600
            if days > 0:
                status = f"{days}天{hours}小时后"
            else:
                status = f"{hours}小时后"

        solution_preview = entry["solution"].split("\n")[0]
        if len(solution_preview) > 35:
            solution_preview = solution_preview[:35] + "..."

        print(f"  {i:>3}. {due} [{status}] (间隔{interval}天, EF={ef:.1f})")
        print(f"      {kw}")
        print(f"      {solution_preview}")
        print()

    wait_enter()


# ============================================================
#  删除题目
# ============================================================

def delete_entry() -> None:
    clear_screen()
    print("=" * 40)
    print("       删除题目")
    print("=" * 40)
    print()
    data = load_data()
    if not data:
        print("  题库为空。")
        wait_enter()
        return

    for i, entry in enumerate(data, 1):
        interval = entry.get("interval", 0)
        ef = entry.get("ef", 2.5)
        print(f"  [{i}] {entry['keyword']} (间隔{interval}天, EF={ef:.1f})")

    print()
    choice = input("  请输入要删除的编号 (0 取消): ").strip()
    try:
        idx = int(choice)
    except ValueError:
        wait_enter("  无效输入。按回车键返回...")
        return

    if idx == 0:
        return
    if 1 <= idx <= len(data):
        removed = data.pop(idx - 1)
        save_data(data)
        print(f"\n  已删除「{removed['keyword']}」。")
        wait_enter()
    else:
        wait_enter("  编号无效。按回车键返回...")


# ============================================================
#  重置复习进度
# ============================================================

def reset_progress() -> None:
    clear_screen()
    print("=" * 40)
    print("       重置复习进度")
    print("=" * 40)
    print()
    confirm = input("  确认将所有题目的 SM-2 数据归零? (y/n): ").strip().lower()
    if confirm == "y":
        data = load_data()
        now = int(time.time())
        for entry in data:
            entry["next_review"] = now
            entry["interval"] = 0
            entry["ef"] = 2.5
        save_data(data)
        print("\n  已重置所有复习进度。")
    else:
        print("\n  已取消。")
    wait_enter()


# ============================================================
#  科目筛选
# ============================================================

def select_subject(subjects: list[str]) -> int:
    """显示科目选择菜单，返回用户选择的索引。
    0 表示全部科目，1..n 表示对应科目。
    """
    clear_screen()
    print("=" * 40)
    print("       选择科目")
    print("=" * 40)
    print()
    print("  [0] 全部科目")
    for i, subject in enumerate(subjects, 1):
        print(f"  [{i}] {subject}")
    print()
    choice = input(f"  请选择科目 (0-{len(subjects)}): ").strip()
    try:
        idx = int(choice)
        if 0 <= idx <= len(subjects):
            return idx
    except ValueError:
        pass
    wait_enter("  输入无效，默认选择全部科目。按回车键继续...")
    return 0


# ============================================================
#  测试模式（核心）
# ============================================================

def start_test() -> None:
    data = load_data()
    if not data:
        clear_screen()
        print("  题库为空，请先录入题目。")
        wait_enter()
        return

    now = int(time.time())

    # ── 科目筛选 ──
    subjects = get_subjects(data)
    selected_subject: Optional[str] = None
    if subjects:
        idx = select_subject(subjects)
        if idx > 0:
            selected_subject = subjects[idx - 1]

    # ── 筛选到期题目（next_review <= 当前时间戳）──
    due_entries = [
        e for e in data
        if e.get("next_review", now) <= now
    ]
    if selected_subject:
        due_entries = [
            e for e in due_entries
            if extract_subject(e["keyword"]) == selected_subject
        ]

    if not due_entries:
        clear_screen()
        if selected_subject:
            print(f"  科目「{selected_subject}」下没有待复习的题目。")
        else:
            print("  当前没有待复习的题目。")
        total = len(data)
        print(f"  题库共 {total} 题，均已掌握或尚未到复习时间。")
        print()
        wait_enter()
        return

    # ── 开始界面 ──
    clear_screen()
    print("=" * 40)
    print("       条件反射测试")
    print("=" * 40)
    if selected_subject:
        print(f"       当前科目: {selected_subject}")
    print(f"       待复习: {len(due_entries)} 题")
    print()
    print("  每题将由 AI 根据关键词实时生成一道变式题。")
    print("  你需要在心中作答，然后对照标准解析。")
    print("  测试过程中可随时输入 q 退出。")
    wait_enter()

    count = 0
    correct = 0
    incorrect = 0

    for idx_in_list, entry in enumerate(due_entries):
        clear_screen()
        print("=" * 40)
        print("       条件反射测试")
        print("=" * 40)
        if selected_subject:
            print(f"       当前科目: {selected_subject}")
        print(f"       进度: {idx_in_list + 1}/{len(due_entries)}")
        print(f"       正确: {correct}  |  错误: {incorrect}")
        print()

        keyword = entry["keyword"]
        print("  " + "-" * 36)
        print(f"  【知识点】: {keyword}")
        print("  " + "-" * 36)

        # ── 调用 DeepSeek API 生成变式题 ──
        result = generate_question(keyword)
        if result is None:
            print("\n  生成题目失败，跳过此题。")
            wait_enter()
            continue

        # ── 显示变式题 ──
        print()
        print("  " + "=" * 36)
        print("  【变式题】")
        print("  " + "-" * 36)
        for line in result["question"].split("\n"):
            print(f"  {line}")
        print("  " + "=" * 36)
        print()

        # ── 用户思考后按回车查看解析 ──
        user_input = input("  思考完毕后按回车键查看标准解析 (q 退出)...").strip()
        if user_input.lower() == "q":
            print("\n  已退出测试。")
            break

        # ── 显示标准解析 ──
        print()
        print("  " + "=" * 36)
        print("  【标准解析】")
        print("  " + "-" * 36)
        for line in result["solution"].split("\n"):
            print(f"  {line}")
        print("  " + "=" * 36)
        print()

        # ── 询问是否做对 ──
        while True:
            answer = input("  你是否做对了? (y=正确 / n=错误 / q=退出): ").strip().lower()
            if answer == "q":
                print("\n  已退出测试。")
                # 退出前保存已更新的数据
                save_data(data)
                return
            if answer in ("y", "n"):
                break
            print("  请输入 y 或 n。")

        is_correct = (answer == "y")
        if is_correct:
            correct += 1
        else:
            incorrect += 1

        # ── 更新 SM-2 数据 ──
        sm2_update(entry, is_correct)
        save_data(data)
        count += 1

    # ── 测试结束 ──
    clear_screen()
    print("=" * 40)
    print("       测试结束")
    print("=" * 40)
    print()
    if selected_subject:
        print(f"  科目: {selected_subject}")
    print(f"  共测试: {count} 题")
    print(f"  正确: {correct}")
    print(f"  错误: {incorrect}")
    if count > 0:
        print(f"  正确率: {correct / count * 100:.1f}%")
    print()
    wait_enter()


# ============================================================
#  主入口
# ============================================================

def main() -> None:
    while True:
        choice = menu()
        if choice == "1":
            add_entry()
        elif choice == "2":
            start_test()
        elif choice == "3":
            view_entries()
        elif choice == "4":
            delete_entry()
        elif choice == "5":
            reset_progress()
        elif choice == "6":
            clear_screen()
            print("  再见！")
            break
        else:
            print("  无效选择，请重新输入。")
            wait_enter()


if __name__ == "__main__":
    main()
