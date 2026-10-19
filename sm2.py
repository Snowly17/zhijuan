# -*- coding: utf-8 -*-
"""SM-2 遗忘曲线算法"""
from datetime import date, timedelta, datetime


def update_sm2(ease, interval_days, repetitions, quality):
    """
    quality: 0—5
      0-2 表示答错（重置）
      3   勉强答对
      4   答对
      5   轻松答对
    返回：新的 (ease, interval_days, repetitions, next_review)
    """
    if quality < 3:
        # 答错：重置
        repetitions = 0
        interval_days = 1
    else:
        # 答对：推进
        if repetitions == 0:
            interval_days = 1
        elif repetitions == 1:
            interval_days = 6
        else:
            interval_days = int(round(interval_days * ease))
        repetitions += 1

    # 更新难度系数
    ease = ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ease = max(1.3, ease)

    next_review = (datetime.now() + timedelta(days=interval_days)).strftime("%Y-%m-%d")
    return round(ease, 2), interval_days, repetitions, next_review


def get_today_review(db):
    """获取今日需要复习的错题"""
    today = datetime.now().strftime("%Y-%m-%d")
    return db.execute(
        "SELECT * FROM wrong_book "
        "WHERE next_review IS NULL OR next_review <= ? "
        "ORDER BY next_review, paper_name, id",
        (today,)
    ).fetchall()