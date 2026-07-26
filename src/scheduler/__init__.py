"""OSスケジューラ（cron/systemd/launchd）への自動登録機能。

setupスキル（`.agent/skills/setup.md`）が config.yaml に保存する
`schedule.timezone` / `schedule.times` を、実際のOSスケジューラへ冪等に
登録するためのモジュール群。CLIエントリポイントは `src/cli.py` の
`schedule` サブコマンドから利用する。

本パッケージのエラーハンドリング方針は、リポジトリ全体の「部分失敗を
握りつぶし縮退配信する」方針とは異なり、失敗時は例外を送出して
呼び出し元（CLI）に明確な失敗シグナルを返す設計とする。
"""

from __future__ import annotations
