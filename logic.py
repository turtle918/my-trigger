"""解题条件反射训练器 —— 核心逻辑模块。

包含 SM-2 记忆算法、DeepSeek API 出题、数据读写及科目辅助函数。
数据持久化使用 Supabase 云数据库，彻底抛弃本地 JSON 文件。
"""

import json
import os
import time
from typing import Optional, Any

import requests
import streamlit as st
from dotenv import load_dotenv
from supabase import create_client, Client

# 加载 .env 中的环境变量
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))


def _get_secret(key: str, default=None) -> Optional[str]:
    """优先从 st.secrets 读取密钥，失败则回退到 os.getenv()。

    这样本地开发（.env）和 Streamlit Cloud（st.secrets）均可正常工作。
    """
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, default)


DEEPSEEK_API_KEY = _get_secret("DEEPSEEK_API_KEY")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# ── Supabase 客户端（全局单例） ──
SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = _get_secret("SUPABASE_KEY")

_supabase: Optional[Client] = None


def _get_supabase() -> Client:
    """获取 Supabase 客户端实例（延迟初始化，便于测试和迁移）。"""
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "未配置 SUPABASE_URL 或 SUPABASE_KEY，请检查 .env 文件。\n"
                "在 Supabase 项目面板 → Settings → API 中可获取这两个值。"
            )
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


TABLE_NAME = "flashcards"


# ============================================================
#  SM-2 艾宾浩斯记忆算法
# ============================================================

def sm2_update(entry: dict, correct: bool) -> None:
    """按 SM-2 算法更新一道题的复习数据。

    正确时：增加 interval 并重新计算 next_review。
    错误时：interval 重置为 1，降低 ef，next_review 设为 1 天后。
    """
    now = int(time.time())

    if correct:
        interval = entry["interval"]
        if interval == 0:
            interval = 1
        elif interval == 1:
            interval = 6
        else:
            interval = round(interval * entry["ef"])
        # quality = 5 (perfect response)
        entry["ef"] = max(1.3, entry["ef"] + 0.1)
        entry["interval"] = interval
    else:
        entry["interval"] = 1
        entry["ef"] = max(1.3, entry["ef"] - 0.2)

    entry["next_review"] = now + entry["interval"] * 86400


# ============================================================
#  数据读写
# ============================================================

def load_data() -> list[dict]:
    """从 Supabase 云数据库加载全部题目。

    返回包含 keyword / solution / next_review / interval / ef 的字典列表。
    按 created_at 升序排列以保证顺序稳定。
    """
    supabase = _get_supabase()
    resp = (
        supabase.table(TABLE_NAME)
        .select("keyword", "solution", "next_review", "interval", "ef")
        .order("created_at", desc=False)
        .execute()
    )
    rows = resp.data or []
    # 将 interval 转为 int, ef 转为 float（Supabase 可能返回字符串形式的数字）
    for row in rows:
        row["interval"] = int(row["interval"])
        row["ef"] = float(row["ef"])
    return rows


def save_data(data: list[dict]) -> None:
    """将全部题目全量写入 Supabase 云数据库。

    先清空整个表，再逐批插入，实现完整的数据替换。
    遵循"删旧插新"策略，保证本地数据与云端一致。
    """
    supabase = _get_supabase()

    # 1) 清空表（删除所有行）
    #    Supabase 要求 DELETE 必须带过滤条件，这里用 id 不为空来匹配全部行
    supabase.table(TABLE_NAME).delete().neq("keyword", "__NO_SUCH_KEYWORD__").execute()

    # 2) 批量插入新数据
    if not data:
        return

    # 每次最多插入 500 行（Supabase REST API 限制）
    batch_size = 500
    for i in range(0, len(data), batch_size):
        batch = data[i : i + batch_size]
        supabase.table(TABLE_NAME).insert(batch).execute()


# ============================================================
#  DeepSeek API —— 根据关键词生成变式题
# ============================================================

def generate_question(keyword: str) -> dict[str, Any]:
    """调用 DeepSeek API 根据 keyword 生成一道变式题和标准解析。

    成功时返回 {"question": str, "solution": str}。
    失败时返回 {"error": str, "detail": str, ...}，方便调用方展示具体原因。
    """
    if not DEEPSEEK_API_KEY:
        msg = "未找到 DEEPSEEK_API_KEY，请检查 .env 或 st.secrets 配置。"
        print(f"\n  错误: {msg}")
        return {"error": msg, "detail": "DEEPSEEK_API_KEY 为空"}

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = (
        "你是一个高考理科复习专家。你的任务是根据给定的知识点，提取出最典型的抽象题目特征作为触发条件。"
        "你需要给出学生看到该特征时应该产生的第一反应和核心处理动作。"
        "绝对不要生成具体的带有数字的计算题。只提供逻辑映射机制。"
    )

    user_prompt = (
        f"请根据知识点：{keyword}，生成一个条件反射训练卡片。\n\n"
        f"要求：\n"
        f"1. question 字段输出一个典型的题目文字特征或结构特征。例如：'题目中出现\"方程 f(x)=a 有三个不同实数根\"。\n"
        f"2. solution 字段输出对应的核心处理动作。例如：'动作：分离参数 a。将问题转化为 y=a 与 y=f(x) 图像的交点问题。对 f(x) 求导寻找极值点。'\n\n"
        f"请严格输出 JSON 格式：{{\"question\": \"...\", \"solution\": \"...\"}}"
    )

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 4096,
    }

    try:
        print("\n  ⏳ 正在调用 DeepSeek API 生成题目...")
        resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=120)

        # 非 200 状态码：收集完整错误信息再返回，不直接 raise
        if not resp.ok:
            status_code = resp.status_code
            try:
                error_body = resp.json()
            except Exception:
                error_body = resp.text
            return {
                "error": f"DeepSeek API 返回 HTTP {status_code}",
                "status_code": status_code,
                "detail": json.dumps(error_body, ensure_ascii=False) if isinstance(error_body, dict) else str(error_body),
            }

        body = resp.json()
        content = body["choices"][0]["message"]["content"].strip()

        # 如果被 markdown 代码块包裹，去除包裹标记
        if content.startswith("```"):
            lines = content.split("\n")
            start = 0
            end = len(lines)
            for i, line in enumerate(lines):
                if line.strip().startswith("```"):
                    start = i + 1
                    break
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith("```"):
                    end = i
                    break
            content = "\n".join(lines[start:end]).strip()

        result = json.loads(content)
        return {
            "question": result.get("question", ""),
            "solution": result.get("solution", ""),
        }

    except requests.RequestException as e:
        msg = f"网络请求异常: {e}"
        print(f"\n  {msg}")
        return {"error": msg, "detail": str(e)}
    except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as e:
        msg = f"API 返回内容解析失败: {e}"
        print(f"\n  {msg}")
        return {"error": msg, "detail": str(e)}
    except Exception as e:
        # 兜底：确保任何意外异常都返回字典，绝不泄露 None
        msg = f"未知错误: {type(e).__name__}: {e}"
        print(f"\n  {msg}")
        return {"error": msg, "detail": str(e)}


# ============================================================
#  科目筛选辅助函数
# ============================================================

def extract_subject(keyword: str) -> str:
    """提取 keyword 开头方括号内的科目名称，若无则返回空字符串。"""
    if keyword.startswith("["):
        end = keyword.find("]")
        if end != -1:
            return keyword[1:end]
    return ""


def get_subjects(data: list[dict]) -> list[str]:
    """从题库中提取所有不重复的科目名称。"""
    subjects = set()
    for entry in data:
        subject = extract_subject(entry["keyword"])
        if subject:
            subjects.add(subject)
    return sorted(subjects)


# ============================================================
#  错题筛选 —— 用于穿插复习
# ============================================================

def get_weak_cards(data: list[dict], exclude_keyword: str = "", limit: int = 5) -> list[dict]:
    """返回 ef 最低的到期题目列表，供错题穿插使用。

    按 ef 升序排列（越低的越弱），只返回 next_review 已到期的卡片。
    exclude_keyword 用于排除当前正在做的题目，避免立即重复。
    """
    now = int(time.time())
    due = [e for e in data if e.get("next_review", now) <= now]
    if exclude_keyword:
        due = [e for e in due if e["keyword"] != exclude_keyword]
    due.sort(key=lambda e: e.get("ef", 2.5))
    return due[:limit]


# ============================================================
#  统计辅助函数
# ============================================================

def count_due(data: list[dict]) -> int:
    """返回待复习题目数量（next_review <= 当前时间戳）。"""
    now = int(time.time())
    return sum(1 for e in data if e.get("next_review", now) <= now)
