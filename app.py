"""解题条件反射训练器 —— Streamlit 网页界面。

使用 streamlit run app.py 启动，支持手机浏览器通过局域网 IP 访问。
"""

import random
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from logic import (
    load_data,
    save_data,
    generate_question,
    sm2_update,
    extract_subject,
    get_subjects,
    count_due,
    get_weak_cards,
)


# ============================================================
#  页面配置
# ============================================================

st.set_page_config(
    page_title="条件反射训练器",
    page_icon="🧠",
    layout="wide",
)


# ============================================================
#  初始化 session_state
# ============================================================

def init_session():
    """初始化 session_state 中的变量。"""
    defaults = {
        "test_active": False,
        "current_entry": None,
        "current_question": None,
        "current_solution": None,
        "show_solution": False,
        "due_entries": [],
        "due_index": 0,
        "test_correct": 0,
        "test_incorrect": 0,
        "test_count": 0,
        "selected_subject": None,
        "answer_submitted": False,
        "filter_subject": "全部科目",
        # 错题穿插
        "question_counter": 0,
        "INTERLEAVE_INTERVAL": 5,
        "_interleaved": False,
        # 历史视图
        "history_filter": "all",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session()


# ============================================================
#  侧边栏
# ============================================================

def render_sidebar():
    """渲染侧边栏：统计信息。"""
    with st.sidebar:
        st.title("📊 统计")

        data = load_data()
        total = len(data)
        due = count_due(data)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("题库总数", total)
        with col2:
            st.metric("待复习", due)

        st.divider()

        # 科目筛选
        subjects = get_subjects(data)
        subject_options = ["全部科目"] + subjects
        selected = st.selectbox(
            "科目筛选",
            subject_options,
            index=subject_options.index(st.session_state.filter_subject)
            if st.session_state.filter_subject in subject_options
            else 0,
        )
        if selected != st.session_state.filter_subject:
            st.session_state.filter_subject = selected
            st.rerun()

        st.divider()

        # 操作按钮
        st.subheader("⚙️ 操作")
        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()

        if st.button("🛑 结束当前测试", use_container_width=True):
            st.session_state.test_active = False
            st.session_state.current_entry = None
            st.session_state.current_question = None
            st.session_state.current_solution = None
            st.session_state.show_solution = False
            st.session_state.answer_submitted = False
            st.rerun()


# ============================================================
#  主界面 —— 空闲状态
# ============================================================

def render_idle():
    """显示空闲状态：可以开始新测试。"""
    st.title("🧠 解题条件反射训练器")
    st.caption("SM-2 艾宾浩斯记忆算法 + DeepSeek API 动态出题")

    data = load_data()
    due = count_due(data)

    if not data:
        st.info("📭 题库为空。请先通过命令行 `python trigger.py` 录入题目。")
        return

    if due == 0:
        st.success("🎉 当前没有待复习的题目，均已掌握！")
        total = len(data)
        st.write(f"题库共 {total} 题。")
        return

    # 筛选到期题目
    now = int(time.time())

    filter_subj = st.session_state.filter_subject
    due_entries = [e for e in data if e.get("next_review", now) <= now]
    if filter_subj != "全部科目":
        due_entries = [e for e in due_entries if extract_subject(e["keyword"]) == filter_subj]

    if not due_entries:
        st.success(f"🎉 科目「{filter_subj}」下没有待复习的题目！")
        return

    st.write(f"当前待复习 **{len(due_entries)}** 题（共 {len(data)} 题）")

    if st.button("▶️ 开始测试", type="primary", use_container_width=True):
        st.session_state.test_active = True
        st.session_state.due_entries = due_entries
        st.session_state.due_index = 0
        st.session_state.test_correct = 0
        st.session_state.test_incorrect = 0
        st.session_state.test_count = 0
        st.session_state.current_entry = due_entries[0]
        st.session_state.current_question = None
        st.session_state.current_solution = None
        st.session_state.show_solution = False
        st.session_state.answer_submitted = False
        st.session_state.question_counter = 0
        st.session_state._interleaved = False
        st.rerun()


# ============================================================
#  主界面 —— 测试状态
# ============================================================

def render_test():
    """显示测试状态：题目 → 思考 → 解析 → 判断。"""
    st.title("🧠 条件反射测试")

    # 进度条
    total = len(st.session_state.due_entries)
    current_idx = st.session_state.due_index
    progress = (current_idx) / total if total > 0 else 1.0
    st.progress(progress, text=f"进度: {current_idx}/{total}")

    # 统计行
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("正确", st.session_state.test_correct)
    with col2:
        st.metric("错误", st.session_state.test_incorrect)
    with col3:
        accuracy = (
            st.session_state.test_correct / st.session_state.test_count * 100
            if st.session_state.test_count > 0
            else 0
        )
        st.metric("正确率", f"{accuracy:.1f}%")

    st.divider()

    entry = st.session_state.current_entry
    if entry is None:
        st.error("没有更多题目了。")
        return

    # 显示知识点
    keyword = entry["keyword"]
    st.subheader("📌 知识点")
    st.info(keyword)

    # 错题穿插提示
    if st.session_state.get("_interleaved", False):
        st.warning("⚠️ 错题穿插复习 —— 这道题是你的弱项，请多加注意！")

    # 生成题目按钮（如果还没生成）
    if st.session_state.current_question is None:
        with st.spinner("🤖 正在调用 DeepSeek API 生成变式题..."):
            result = generate_question(keyword)
            # 安全检查：确保 result 是 dict 再使用 in 操作符
            if not isinstance(result, dict):
                st.error(f"❌ 生成题目失败 —— 函数返回了异常类型: {type(result).__name__}")
                if st.button("⏭️ 跳过此题"):
                    advance_to_next()
                    st.rerun()
                return
            if "error" in result:
                # 显示详细错误信息，方便排查
                st.error(f"❌ 生成题目失败 —— {result['error']}")
                # 如果有 HTTP 状态码，单独高亮
                if "status_code" in result:
                    st.warning(f"HTTP 状态码: {result['status_code']}")
                # 展示 API 返回的原始错误详情
                with st.expander("🔍 查看错误详情"):
                    st.code(result.get("detail", "无额外信息"), language="json")
                if st.button("⏭️ 跳过此题"):
                    advance_to_next()
                    st.rerun()
                return
            st.session_state.current_question = result["question"]
            st.session_state.current_solution = result["solution"]
        st.rerun()

    # 显示变式题
    st.subheader("📝 变式题")
    st.markdown(
        f"""<div style="
            background-color:#2d2d2d;
            color:#ffffff;
            font-weight:bold;
            padding:20px;
            border-radius:8px;
            font-size:17px;
            line-height:2.0;
            border-left:4px solid #ff6b6b;
        ">
        {st.session_state.current_question.replace(chr(10), '<br>')}
        </div>""",
        unsafe_allow_html=True,
    )

    st.write("")
    st.caption("💡 在心中思考答案，然后点击下方按钮查看标准解析。")

    # 显示解析按钮
    if not st.session_state.show_solution:
        if st.button("🔍 查看标准解析", type="primary", use_container_width=True):
            st.session_state.show_solution = True
            st.rerun()

    # 显示解析和判断按钮
    if st.session_state.show_solution:
        st.divider()
        st.subheader("📖 标准解析")
        st.markdown(
            f"""<div style="
                background-color:#1a3320;
                color:#d4ffd4;
                font-weight:bold;
                padding:20px;
                border-radius:8px;
                font-size:17px;
                line-height:2.0;
                border-left:4px solid #4caf50;
            ">
            {st.session_state.current_solution.replace(chr(10), '<br>')}
            </div>""",
            unsafe_allow_html=True,
        )

        st.divider()

        if not st.session_state.answer_submitted:
            st.subheader("✅ 判断结果")
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("👍 我做对了", type="primary", use_container_width=True):
                    submit_answer(True)
            with col2:
                if st.button("👎 我做错了", type="secondary", use_container_width=True):
                    submit_answer(False)
            with col3:
                if st.button("⏭️ 跳过", use_container_width=True):
                    advance_to_next()
                    st.rerun()
        else:
            st.success("✅ 已记录！" if st.session_state.get("_last_correct", True) else "📝 已记录，继续加油！")
            if st.button("▶️ 下一题", type="primary", use_container_width=True):
                advance_to_next()
                st.rerun()


# ============================================================
#  辅助函数
# ============================================================

def submit_answer(correct: bool):
    """提交答案并更新 SM-2 数据。"""
    entry = st.session_state.current_entry
    if entry:
        sm2_update(entry, correct)
        data = load_data()
        for i, e in enumerate(data):
            if e["keyword"] == entry["keyword"]:
                data[i] = entry
                break
        save_data(data)

        st.session_state.test_count += 1
        if correct:
            st.session_state.test_correct += 1
        else:
            st.session_state.test_incorrect += 1

        st.session_state.answer_submitted = True
        st.session_state._last_correct = correct
        st.rerun()


def advance_to_next():
    """前进到下一道题，并在每 N 题后强制穿插一道错题。"""
    st.session_state.due_index += 1
    st.session_state.question_counter += 1

    if st.session_state.due_index >= len(st.session_state.due_entries):
        # 测试结束
        st.session_state.test_active = False
        st.session_state.current_entry = None
        st.session_state.current_question = None
        st.session_state.current_solution = None
        st.session_state.show_solution = False
        st.session_state.answer_submitted = False
        return

    # ── 错题穿插检查 ──
    interleaved = False
    if st.session_state.question_counter >= st.session_state.INTERLEAVE_INTERVAL:
        # 从数据库拉取弱项卡片（ef 最低的到期题目）
        data = load_data()
        current_kw = st.session_state.due_entries[st.session_state.due_index]["keyword"]
        weak_cards = get_weak_cards(data, exclude_keyword=current_kw, limit=3)
        if weak_cards:
            card = random.choice(weak_cards)
            st.session_state.due_entries.insert(st.session_state.due_index, card)
            interleaved = True
        # 无论是否找到错题，都重置计数器，开始新一轮计数
        st.session_state.question_counter = 0

    st.session_state._interleaved = interleaved
    st.session_state.current_entry = st.session_state.due_entries[st.session_state.due_index]
    st.session_state.current_question = None
    st.session_state.current_solution = None
    st.session_state.show_solution = False
    st.session_state.answer_submitted = False


# ============================================================
#  测试完成界面
# ============================================================

def render_complete():
    """显示测试完成总结。"""
    st.title("🎉 本轮测试完成！")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("共测试", st.session_state.test_count)
    with col2:
        st.metric("正确", st.session_state.test_correct)
    with col3:
        st.metric("错误", st.session_state.test_incorrect)
    with col4:
        accuracy = (
            st.session_state.test_correct / st.session_state.test_count * 100
            if st.session_state.test_count > 0
            else 0
        )
        st.metric("正确率", f"{accuracy:.1f}%")

    # 数据已实时保存，无需额外操作
    st.success("✅ 所有复习进度已自动保存。")

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 开始新一轮测试", type="primary", use_container_width=True):
            st.session_state.test_active = False
            st.session_state.due_entries = []
            st.session_state.due_index = 0
            st.session_state.test_correct = 0
            st.session_state.test_incorrect = 0
            st.session_state.test_count = 0
            st.session_state.current_entry = None
            st.session_state.current_question = None
            st.session_state.current_solution = None
            st.session_state.show_solution = False
            st.session_state.answer_submitted = False
            st.rerun()
    with col2:
        if st.button("🏠 返回主页", use_container_width=True):
            st.session_state.test_active = False
            st.session_state.due_entries = []
            st.session_state.due_index = 0
            st.session_state.test_correct = 0
            st.session_state.test_incorrect = 0
            st.session_state.test_count = 0
            st.session_state.current_entry = None
            st.session_state.current_question = None
            st.session_state.current_solution = None
            st.session_state.show_solution = False
            st.session_state.answer_submitted = False
            st.rerun()


# ============================================================
#  历史视图
# ============================================================

def render_history():
    """在独立 Tab 中展示题库全貌，支持按弱项 / 待复习筛选。"""
    st.title("📋 题库浏览")

    data = load_data()

    if not data:
        st.info("📭 题库为空。请先通过命令行 `python trigger.py` 录入题目。")
        return

    # ── 筛选按钮行 ──
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📚 全部题目", use_container_width=True):
            st.session_state.history_filter = "all"
    with col2:
        if st.button("⚠️ 弱项 (ef < 2.0)", use_container_width=True):
            st.session_state.history_filter = "weak"
    with col3:
        if st.button("⏰ 待复习", use_container_width=True):
            st.session_state.history_filter = "due"

    now = int(time.time())

    filter_mode = st.session_state.history_filter
    if filter_mode == "weak":
        filtered = [e for e in data if e.get("ef", 2.5) < 2.0]
    elif filter_mode == "due":
        filtered = [e for e in data if e.get("next_review", now) <= now]
    else:
        filtered = data

    st.caption(f"当前筛选：**{_filter_label(filter_mode)}**  ·  共 **{len(filtered)}** 条记录")

    if not filtered:
        st.success("🎉 没有符合条件的记录！")
        return

    # ── 构建 DataFrame ──
    rows = []
    for e in filtered:
        nr = e.get("next_review", 0)
        nr_str = datetime.fromtimestamp(nr).strftime("%Y-%m-%d %H:%M") if nr else "-"
        rows.append({
            "知识点": e.get("keyword", ""),
            "解析（前80字）": _truncate(e.get("solution", ""), 80),
            "下次复习": nr_str,
            "间隔(天)": e.get("interval", 0),
            "EF": round(e.get("ef", 2.5), 1),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)


def _filter_label(mode: str) -> str:
    """将筛选模式转为中文标签。"""
    return {"all": "全部题目", "weak": "弱项 (ef < 2.0)", "due": "待复习"}.get(mode, mode)


def _truncate(text: str, max_len: int) -> str:
    """截断过长的文本，超出部分用 … 表示。"""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ============================================================
#  主入口
# ============================================================

def main():
    render_sidebar()

    tab1, tab2 = st.tabs(["🧠 训练", "📋 题库浏览"])

    with tab1:
        if not st.session_state.test_active:
            render_idle()
        elif st.session_state.current_entry is None:
            render_complete()
        else:
            render_test()

    with tab2:
        render_history()


if __name__ == "__main__":
    main()
