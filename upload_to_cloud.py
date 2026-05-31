#!/usr/bin/env python3
"""一次性迁移脚本：将本地 data.json 的全部记录推送到 Supabase 云数据库。

用法：
    python upload_to_cloud.py

前置条件：
    1. 已创建 Supabase 项目并执行建表 SQL。
    2. .env 文件中已正确配置 SUPABASE_URL 和 SUPABASE_KEY。
    3. 本地 data.json 文件存在且格式正确。

执行效果：
    - 读取 data.json 中的全部记录
    - 全量推送到 Supabase 的 flashcards 表
    - 校验云端数据条数与本地一致
    - 校验通过后删除本地 data.json

如需回滚：在删除前脚本会要求确认，你可以拒绝并保留 data.json。
"""

import json
import os
import sys

# 修复 Windows 终端 GBK 编码下 emoji 输出问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

# 将项目根目录加入 sys.path
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# 加载 .env
load_dotenv(os.path.join(PROJECT_DIR, ".env"))

# 直接初始化 Supabase（不依赖 logic.py 的全局单例）
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("[ERROR] 未找到 SUPABASE_URL 或 SUPABASE_KEY。")
    print("        请在 .env 文件中配置这两个环境变量。")
    print("        格式如下：")
    print("          SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co")
    print("          SUPABASE_KEY=eyJhbGciOiJI...  (service_role key)")
    sys.exit(1)

# 去掉末尾斜杠
SUPABASE_URL = SUPABASE_URL.rstrip("/")

# 简单的 emoji 安全输出标记
OK = "[OK]"
ERR = "[ERROR]"
WARN = "[WARN]"
WAIT = "[...]"

print("=" * 55)
print("  解题条件反射训练器 - 云端迁移脚本")
print("=" * 55)
print()
print(f"  Supabase URL: {SUPABASE_URL}")
print(f"  Key 前缀:    {SUPABASE_KEY[:20]}...")
print()

# ── 1. 读取本地数据 ──
DATA_FILE = os.path.join(PROJECT_DIR, "data.json")

if not os.path.exists(DATA_FILE):
    print(f"{ERR} 未找到 data.json 文件。")
    print(f"    期望位置: {DATA_FILE}")
    sys.exit(1)

with open(DATA_FILE, "r", encoding="utf-8") as f:
    local_data = json.load(f)

if not isinstance(local_data, list):
    print(f"{ERR} data.json 格式不正确，期望 JSON 数组。")
    sys.exit(1)

local_count = len(local_data)
print(f"  {OK} 成功读取本地 data.json: {local_count} 条记录")

# 快速校验数据结构
required_fields = ["keyword", "solution", "next_review", "interval", "ef"]
for i, entry in enumerate(local_data):
    missing = [f for f in required_fields if f not in entry]
    if missing:
        print(f"  {ERR} 第 {i+1} 条记录缺少字段: {missing}")
        print(f"      内容: {entry}")
        sys.exit(1)

print(f"  {OK} 数据格式校验通过（所有 {local_count} 条记录字段完整）")
print()

# ── 2. 连接 Supabase ──
print(f"  {WAIT} 正在连接 Supabase...")
try:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    # 快速冒烟测试：查询表是否存在
    supabase.table("flashcards").select("keyword", count="exact").limit(0).execute()
    print(f"  {OK} 成功连接 Supabase，flashcards 表可访问")
except Exception as e:
    print(f"  {ERR} 连接或查询 Supabase 失败: {e}")
    print()
    print("  请检查以下事项：")
    print("    1. SUPABASE_URL 和 SUPABASE_KEY 是否正确")
    print("    2. 是否已在 Supabase 中创建 flashcards 表（见下方 SQL）")
    print("    3. 网络是否能访问 supabase.co 域名")
    print()
    print("  -- 建表 SQL（在 Supabase SQL Editor 中执行）--")
    print("""
    CREATE TABLE IF NOT EXISTS flashcards (
      id         BIGSERIAL PRIMARY KEY,
      keyword    TEXT NOT NULL UNIQUE,
      solution   TEXT NOT NULL DEFAULT '',
      next_review BIGINT NOT NULL DEFAULT 0,
      interval   INTEGER NOT NULL DEFAULT 0,
      ef         REAL NOT NULL DEFAULT 2.5,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE INDEX IF NOT EXISTS idx_flashcards_next_review ON flashcards(next_review);
    CREATE INDEX IF NOT EXISTS idx_flashcards_keyword ON flashcards(keyword);

    -- 关闭 RLS 或创建宽松策略（个人单用户应用）
    ALTER TABLE flashcards ENABLE ROW LEVEL SECURITY;
    CREATE POLICY "Allow all" ON flashcards FOR ALL USING (true) WITH CHECK (true);
    """)
    sys.exit(1)

print()

# ── 3. 确认操作 ──
print(f"  即将执行以下操作：")
print(f"     1. 将 {local_count} 条记录推送到 Supabase flashcards 表")
print(f"     2. 验证云端数据条数是否与本地一致")
print(f"     3. 验证通过后删除本地 data.json")
print()
confirm = input("  是否继续? (y/n): ").strip().lower()
if confirm != "y":
    print()
    print("  已取消。data.json 未被修改。")
    sys.exit(0)

print()

# ── 4. 推送到 Supabase ──
print(f"  {WAIT} 正在推送 {local_count} 条记录到 Supabase...")

# 4a. 清空云端现有数据
try:
    supabase.table("flashcards").delete().neq("keyword", "__NO_SUCH_KEYWORD__").execute()
    print(f"       -> 已清空云端旧数据")
except Exception as e:
    print(f"       {WARN} 清空云端数据时出现警告（可能表原本为空）: {e}")

# 4b. 批量插入
batch_size = 500
imported = 0
errors = []

for i in range(0, local_count, batch_size):
    batch = local_data[i : i + batch_size]
    try:
        supabase.table("flashcards").insert(batch).execute()
        imported += len(batch)
        print(f"       -> 已推送 {imported}/{local_count} 条...")
    except Exception as e:
        errors.append(f"批次 {i // batch_size + 1} (第 {i+1}-{min(i+batch_size, local_count)} 条) 插入失败: {e}")

if errors:
    print()
    print(f"  {WARN} 推送过程中出现以下错误：")
    for err in errors:
        print(f"       {err}")
    print()
    print("  已推送部分数据。请检查上述错误后重试。")
    print("  data.json 未被删除。")
    sys.exit(1)

print(f"  {OK} 全部 {imported} 条记录推送完毕！")
print()

# ── 5. 验证 ──
print(f"  {WAIT} 正在校验云端数据...")
try:
    resp = supabase.table("flashcards").select("keyword", count="exact").execute()
    cloud_count = resp.count if resp.count is not None else len(resp.data or [])
    print(f"      云端记录数: {cloud_count}")
    print(f"      本地记录数: {local_count}")

    if cloud_count != local_count:
        print()
        print(f"  {ERR} 校验失败: 条数不匹配！云端 {cloud_count} != 本地 {local_count}")
        print("       data.json 未被删除，请检查问题后重试。")
        sys.exit(1)

    print(f"  {OK} 校验通过：条数一致 ({cloud_count})")
except Exception as e:
    print(f"  {ERR} 校验查询失败: {e}")
    print("       data.json 未被删除。")
    sys.exit(1)

print()

# ── 6. 删除本地 data.json ──
print(f"  {WAIT} 正在删除本地 data.json...")
try:
    os.remove(DATA_FILE)
    print(f"  {OK} 已删除 {DATA_FILE}")
except Exception as e:
    print(f"  {ERR} 删除失败: {e}")
    print("      请手动删除该文件。")
    sys.exit(1)

print()
print("=" * 55)
print("  迁移完成！")
print(f"      已从本地 data.json 迁移 {local_count} 条记录到 Supabase 云数据库。")
print(f"      本地数据文件已被安全删除。")
print("      你现在可以放心部署到 Streamlit Community Cloud 了。")
print("=" * 55)
