"""example-blog サンプルスクレイパー。fetch(options, http) -> list[dict] 契約のみ実装する。

src.core.models 等、news-digest本体のモジュールをimportしないこと（疎結合設計）。
標準ライブラリのみ使用（re / html.parser）。

対象HTMLの構造（sample.html参照）:
    <article>
      <h2><a href="...">タイトル</a></h2>
      <time datetime="...">表示用日付</time>
      <p class="summary">要約文</p>
    </article>
を繰り返した一覧ページを想定する。
"""

from __future__ import annotations

import re
from html import unescape

_ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.DOTALL | re.IGNORECASE)
_LINK_RE = re.compile(
    r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>', re.DOTALL | re.IGNORECASE
)
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"', re.IGNORECASE)
_SUMMARY_RE = re.compile(
    r'<p[^>]*class="summary"[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(fragment: str) -> str:
    """タグを除去しHTMLエンティティをデコードし前後の空白を落とす。"""
    return unescape(_TAG_RE.sub("", fragment)).strip()


def fetch(options: dict, http) -> list[dict]:
    response = http.get(options["url"])
    response.raise_for_status()
    html_content = response.text

    records: list[dict] = []
    for article_html in _ARTICLE_RE.findall(html_content):
        link_match = _LINK_RE.search(article_html)
        if not link_match:
            continue
        url = link_match.group(1).strip()
        title = _strip_tags(link_match.group(2))
        if not url or not title:
            continue

        time_match = _TIME_RE.search(article_html)
        published_at = time_match.group(1).strip() if time_match else None

        summary_match = _SUMMARY_RE.search(article_html)
        summary_source = _strip_tags(summary_match.group(1)) if summary_match else ""

        records.append(
            {
                "url": url,
                "title": title,
                "summary_source": summary_source,
                "published_at": published_at,
            }
        )
    return records
