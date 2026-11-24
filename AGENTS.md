# AGENTS.md

OwnTracks Recorder の位置履歴を日別のタイムラインとして表示する Home Assistant カスタム統合です。利用者向けの説明は README.md にあります。

## 開発環境

ツールの版は `mise.toml` と `mise.lock` で固定しています（Python、uv、Node.js、gh-actions-lock、jactionlint、shellcheck）。Python の依存は `uv.lock` で固定しています。

```sh
mise install
uv sync
```

## 検査コマンド

CI（`.github/workflows/ci.yml`）は次のコマンドを別々のジョブで実行し、`status-check` ジョブで結果を集約します。branch protection には `status-check` だけを登録します。

```sh
uv run ruff format --check .
uv run ruff check .
uv run pytest
node --check custom_components/location_timeline/frontend/location-timeline-panel.js
jactionlint
```

整形は `uv run ruff format .`、lint の自動修正は `uv run ruff check --fix .` で行います。`.github/workflows/validate.yml` は hassfest と HACS の検証を実行します。どちらも GitHub Actions 上でだけ動きます。

## ディレクトリ構成

| パス | 内容 |
| --- | --- |
| `custom_components/location_timeline/` | 統合本体。`__init__.py` が設定の読み込みとパネル登録、`views.py` が HTTP API |
| `custom_components/location_timeline/timeline.py`、`geocode.py` | 滞在・移動の推定と逆ジオコーディング。Home Assistant に依存しない |
| `custom_components/location_timeline/frontend/` | パネルの JavaScript。ビルドせずにそのまま配信する。`vendor/` は同梱の Leaflet |
| `scripts/` | 利用者が自分のデータファイルを作るためのスクリプト |
| `tests/` | pytest のテスト |

## 判断基準

`timeline.py` と `geocode.py` から Home Assistant や `aiohttp` を import しないでください。テストは `tests/conftest.py` でこの2ファイルをファイルパスから直接読み込んでおり、パッケージの `__init__.py` を経由すると Home Assistant が必要になります。Home Assistant に依存する処理は `__init__.py` と `views.py` に置きます。

`scripts/` は Python 標準ライブラリだけで、Python 3.12 以降で動くように書きます。README で利用者にそう案内しており、ruff の `target-version`（py314）はこの制約を検査しません。

フロントエンドはビルド工程を持たない素の JavaScript です。`node --check` が検査するのは構文だけなので、パネルの動作は Home Assistant 上で確認します。外部 CDN や外部 API への通信を足さないでください。README のプライバシーの節は、外部への通信を OpenStreetMap の地図タイル取得だけと説明しています。

テストには合成データだけを使います。自分の位置履歴や、Google マップのタイムラインのエクスポートなどそこから作ったデータは、テストにもリポジトリにも入れません。

## GitHub Actions

`uses:` には正確なバージョンタグを書き、コミット SHA は `.github/workflows/actions.lock` で固定します。同じリポジトリの composite action（`.github/actions/setup`）は `uses: $/.github/actions/setup` と書きます。

`uses:` を追加・変更したら、ロックファイルを更新して検証します。`actions.lock` は手で編集しません。

```sh
gh-actions-lock
gh-actions-lock --no-fix
jactionlint
```

## リリース

リリースは `.github/workflows/release.yml`（[easy-release](https://github.com/shun-shobon/easy-release)）で行います。

1. GitHub Actions で Release ワークフローを手動実行し、`patch`・`minor`・`major` のいずれかを選びます。
2. `manifest.json` の `version`、`pyproject.toml` の `version`、`uv.lock` を更新する PR ができるので、確認してマージします。
3. マージすると、タグと GitHub Release が作られて公開されます。

現在のバージョンは既存の Git タグから決まります。`manifest.json` と `pyproject.toml` の `version` を手で変えないでください。easy-release は `manifest.json` を2スペースのインデントで、配列を1要素1行に展開して書き戻します。リリース PR の差分を `version` の1行に保つため、`manifest.json` はこの形で編集します。
