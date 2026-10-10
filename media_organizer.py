#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
D 盘影视资源自动分类整理脚本
================================
功能：
  1. 扫描 D 盘指定目录下的所有视频文件
  2. 按文件名规则自动分类：电影 / 电视剧 / 动漫 / 纪录片 / 其他
  3. 按分辨率（4K / 1080P / 720P / 480P）进一步分子目录
  4. 支持 dry-run 预览模式（不实际移动文件）
  5. 生成整理日志，输出分类统计表

用法：
  python media_organizer.py                # 预览模式（dry-run，不移动文件）
  python media_organizer.py --apply         # 实际执行移动
  python media_organizer.py --src D:\\Videos --dest D:\\Media
  python media_organizer.py --extensions mp4,mkv,avi

依赖：仅 Python 标准库，无需第三方包
"""

import os
import re
import shutil
import argparse
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# ============================================================
# 配置区
# ============================================================

# 默认扫描根目录
DEFAULT_SRC = r"D:\\"
# 默认目标分类根目录
DEFAULT_DEST = r"D:\\Media"

# 支持的视频扩展名
DEFAULT_VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".rmvb", ".flv", ".ts", ".m2ts",
    ".wmv", ".mov", ".mpg", ".mpeg", ".m4v", ".webm", ".vob",
}

# 分类关键词（不区分大小写）
CATEGORY_KEYWORDS = {
    "anime": [
        "anime", "animation", "动画", "动漫", "番剧", "日漫", "国漫",
        "cartoon", "OVA", "OAD",
    ],
    "documentary": [
        "documentary", "纪录片", "BBC", "国家地理", "discovery",
        "nhk", "历史频道",
    ],
}

# 电视剧集数匹配模式（命中任一即判定为电视剧）
TV_PATTERNS = [
    re.compile(r"[Ss]\d{1,2}[._ -]?[Ee]\d{1,3}"),        # S01E01 / S1E01 / S01.E01
    re.compile(r"Season[._ -]\d{1,2}"),                   # Season 1 / Season.02
    re.compile(r"第\s*\d{1,3}\s*[集话]"),                  # 第1集 / 第 12 话
    re.compile(r"EP\s*\d{1,3}", re.IGNORECASE),           # EP01 / EP 12
    re.compile(r"[._ -]\d{1,3}[._ -](?:HD|WEB|BluRay)"),   # .01.HD / -12-WEB
    re.compile(r"电视剧"),
]

# 分辨率匹配
RESOLUTION_PATTERNS = [
    (re.compile(r"2160|4K|UHD", re.IGNORECASE), "4K"),
    (re.compile(r"1080[pi]?|FHD", re.IGNORECASE), "1080P"),
    (re.compile(r"720[pi]?|HD", re.IGNORECASE), "720P"),
    (re.compile(r"480[pi]?|SD", re.IGNORECASE), "480P"),
]

# 年份匹配（19xx / 20xx）
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")

# ============================================================
# 分类逻辑
# ============================================================

def detect_resolution(filename: str) -> str:
    """从文件名识别分辨率，返回 '4K' / '1080P' / '720P' / '480P' / 'Unknown'"""
    for pattern, label in RESOLUTION_PATTERNS:
        if pattern.search(filename):
            return label
    return "Unknown"


def detect_category(filename: str) -> str:
    """
    根据文件名判断大类：
      anime        —— 动漫
      documentary  —— 纪录片
      tv           —— 电视剧
      movie        —— 电影（默认）
    """
    lower = filename.lower()

    # 1. 关键词优先（动漫 / 纪录片）
    for keyword in CATEGORY_KEYWORDS["anime"]:
        if keyword.lower() in lower:
            return "anime"
    for keyword in CATEGORY_KEYWORDS["documentary"]:
        if keyword.lower() in lower:
            return "documentary"

    # 2. 剧集模式匹配 → 电视剧
    for pat in TV_PATTERNS:
        if pat.search(filename):
            return "tv"

    # 3. 其余默认为电影
    return "movie"


def detect_year(filename: str) -> str:
    """从文件名提取年份，找不到返回空字符串"""
    m = YEAR_PATTERN.search(filename)
    return m.group(0) if m else ""


def get_target_path(src_file: Path, dest_root: Path, category: str) -> Path:
    """
    计算目标路径：
      dest_root / 电影 / 1080P / 原文件名
      dest_root / 电视剧 / 4K / 原文件名
    """
    resolution = detect_resolution(src_file.name)
    category_dir = {
        "movie": "电影",
        "tv": "电视剧",
        "anime": "动漫",
        "documentary": "纪录片",
    }.get(category, "其他")

    return dest_root / category_dir / resolution / src_file.name


def resolve_conflict(target: Path) -> Path:
    """如果目标已存在同名文件，自动加 _1、_2 ... 后缀"""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ============================================================
# 扫描与执行
# ============================================================

def scan_videos(src_root: Path, exts: set) -> list[Path]:
    """递归扫描所有视频文件"""
    videos = []
    for dirpath, _, filenames in os.walk(src_root):
        # 跳过目标目录自身，避免重复处理
        if DEFAULT_DEST in Path(dirpath).resolve().parents:
            continue
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in exts:
                videos.append(p)
    return videos


def organize(videos: list[Path], dest_root: Path, apply: bool, logger) -> dict:
    """
    执行分类整理。
    返回统计字典：{ category: count }
    """
    stats = defaultdict(int)
    plan = []  # (src, target, category, resolution)

    for src in videos:
        category = detect_category(src.name)
        resolution = detect_resolution(src.name)
        target = get_target_path(src, dest_root, category)
        target = resolve_conflict(target)
        plan.append((src, target, category, resolution))
        stats[category] += 1

        logger.info(f"[{category:>10s} | {resolution:>7s}] {src}")
        logger.info(f"{' '*26} → {target}")

    if apply:
        logger.info("\n===== 开始实际移动 =====")
        for src, target, _, _ in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            logger.info(f"已移动: {src.name} → {target}")
    else:
        logger.info("\n===== Dry-run 模式：以上为预览，未实际移动文件 =====")
        logger.info("===== 加 --apply 参数可执行实际移动 =====")

    return dict(stats)


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="D 盘影视资源自动分类整理")
    parser.add_argument("--src", default=DEFAULT_SRC, help=f"扫描根目录（默认 {DEFAULT_SRC}）")
    parser.add_argument("--dest", default=DEFAULT_DEST, help=f"分类输出目录（默认 {DEFAULT_DEST}）")
    parser.add_argument("--apply", action="store_true", help="实际执行移动（默认 dry-run 预览）")
    parser.add_argument("--extensions", default=",".join(DEFAULT_VIDEO_EXTS),
                        help="逗号分隔的视频扩展名列表")
    parser.add_argument("--log", default="", help="日志文件路径（默认仅输出到控制台）")
    args = parser.parse_args()

    # 日志配置
    handlers = [logging.StreamHandler()]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=handlers,
    )
    logger = logging.getLogger(__name__)

    src_root = Path(args.src)
    dest_root = Path(args.dest)
    exts = {e.strip().lower() if e.strip().startswith(".") else f".{e.strip().lower()}"
            for e in args.extensions.split(",")}

    if not src_root.exists():
        logger.error(f"源目录不存在: {src_root}")
        return

    logger.info(f"扫描目录: {src_root}")
    logger.info(f"分类输出: {dest_root}")
    logger.info(f"视频扩展名: {sorted(exts)}")
    logger.info(f"执行模式: {'实际移动' if args.apply else '预览 (dry-run)'}")
    logger.info("=" * 60)

    videos = scan_videos(src_root, exts)
    if not videos:
        logger.info("未找到任何视频文件。")
        return

    logger.info(f"共发现 {len(videos)} 个视频文件\n")

    stats = organize(videos, dest_root, args.apply, logger)

    # 输出统计
    logger.info("\n" + "=" * 60)
    logger.info("分类统计：")
    label_map = {"movie": "电影", "tv": "电视剧", "anime": "动漫", "documentary": "纪录片"}
    for cat, count in sorted(stats.items(), key=lambda x: -x[1]):
        logger.info(f"  {label_map.get(cat, cat):>6s} : {count} 个")
    logger.info(f"  {'合计':>6s} : {sum(stats.values())} 个")


if __name__ == "__main__":
    main()
