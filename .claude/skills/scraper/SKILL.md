---
name: scraper
description: news-digestのscraper方式（RSS/Atomを提供しないサイト向け）のスクレイパーを生成・修正するスキル。RSS/Atomのない新しいサイトへの対応を依頼されたとき（生成モード）、または `uv run news-digest --db state/digest.db scrapers check` でスクレイパーの壊れ（status: error/empty）を検知し修正を依頼されたとき（修正モード）に起動する。
---

# news-digest スクレイパー生成・修正代行

このリポジトリのスクレイパー生成・修正手順は `.agents/skills/scraper/SKILL.md` に
記載されています。そのファイルの内容を読み込み、記載されている手順に従って
ユーザーとの対話・スクレイパーの生成または修正を代行してください。
