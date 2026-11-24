# Location Timeline for Home Assistant

[English](#english) | [日本語](#日本語)

## English

A Home Assistant custom integration that adds a sidebar panel showing your [OwnTracks Recorder](https://github.com/owntracks/recorder) location history as a day view similar to Google Maps Timeline: stays, moves coloured by transport mode, and a map.

- The UI text is Japanese.
- Reverse geocoding (area names) covers Japan only.
- Past days can use stays and moves from a Google Maps Timeline export. Later days are inferred from the recorded points.

### Requirements

- Home Assistant 2026.3 or later
- An OwnTracks Recorder that Home Assistant can reach over HTTP without authentication

### Installation

#### Marketplace (Home Assistant 2026.11 or later)

1. Go to **Settings → Marketplace** and select **Add from link**.
2. Enter `https://github.com/tsukuyomi-luna/ha-location-timeline` and add it (type **Integration**).
3. Open **Location Timeline** in the list and select **Install**.
4. Add the YAML configuration below to `configuration.yaml`.
5. Restart Home Assistant.

#### HACS (older Home Assistant versions)

1. In HACS, open ⋮ → **Custom repositories**.
2. Add `https://github.com/tsukuyomi-luna/ha-location-timeline` with type **Integration**.
3. Find **Location Timeline** in HACS and download it.
4. Add the YAML configuration below to `configuration.yaml`.
5. Restart Home Assistant.

#### Manual

1. Copy `custom_components/location_timeline/` to `/config/custom_components/` on your Home Assistant host.
2. Add the YAML configuration below to `configuration.yaml`.
3. Restart Home Assistant.

### Configuration

```yaml
location_timeline:
  recorder_url: http://recorder.local:8083  # OwnTracks Recorder (no auth)
  user: me
  device: phone
  segments_file: location_timeline/google_segments.json  # optional; relative to /config or absolute
  towns_db: location_timeline/towns.sqlite               # optional
  places_file: location_timeline/places.json             # optional
  sidebar_title: タイムライン   # default
  sidebar_icon: mdi:map-clock  # default
  require_admin: true          # default; set false to let non-admin users view the panel
```

Home Assistant starts even if a configured file does not exist; it only logs a warning. The sidecar and places files are reloaded automatically when their modification time changes.

A place name comes from, in order: Home Assistant zones, `places.json`, then the Google `semanticType` (Home → 自宅, Work → 職場). The area name (for example 千代田区丸の内一丁目) comes from `towns.sqlite`.

### Data files

These data files are **not** shipped in this repository. They contain or are derived from your own location data, so never commit them. `.gitignore` blocks the usual file names.

The scripts need only the Python standard library (Python 3.12+).

#### `google_segments.json` (optional)

Built from the Google Maps Timeline on-device export (`Timeline.json`):

```sh
python3 scripts/build_google_sidecar.py Timeline.json /config/location_timeline/google_segments.json
```

#### `towns.sqlite` (optional, reverse geocoding)

Download `latest.csv` from <https://geolonia.github.io/japanese-addresses/latest.csv>, then run:

```sh
python3 scripts/build_towns_db.py latest.csv /config/location_timeline/towns.sqlite
```

The CSV is [Geolonia 住所データ](https://github.com/geolonia/japanese-addresses). The data is licensed under CC BY 4.0 (attribution: "Geolonia 住所データ"); the generator scripts in that repository are MIT. The dataset is no longer updated upstream.

#### `places.json` (optional)

Named places, with lower priority than Home Assistant zones. `radius` is in metres.

```json
[{"name": "ジム", "lat": 35.0, "lon": 139.0, "radius": 100}]
```

### HTTP API

Both endpoints require Home Assistant authentication. With `require_admin: true`, non-admin users get 403.

- `GET /api/location_timeline/day?date=YYYY-MM-DD`: the timeline for that calendar day in Home Assistant's time zone. Without `date`, today. An invalid date returns 400; a failed connection to the Recorder returns 502 (`{"error": "..."}`).
- `GET /api/location_timeline/range`: `{"first": "2026-01-01" | null, "last": "<today>"}`. `first` is the date of the first segment in the sidecar.

### Privacy

- Your coordinates never leave your network. Home Assistant talks only to your Recorder.
- The only external requests are map tile requests from the browser to OpenStreetMap (`tile.openstreetmap.org`). They reveal the viewed map area (tile numbers) and the browser's IP address to the OSM tile servers.
- Leaflet is bundled, so no other CDN is used.
- Do not put data files (sidecar, `places.json`, `Timeline.json`, `towns.sqlite`) under `/config/www/`. Files there are served at `/local/` without authentication. Keep them somewhere like `/config/location_timeline/`; the integration returns data only through the authenticated API.

### License

MIT. See [LICENSE](LICENSE).

The bundled [Leaflet](https://leafletjs.com/) is licensed under BSD-2-Clause; see [`custom_components/location_timeline/frontend/vendor/LICENSE-leaflet`](custom_components/location_timeline/frontend/vendor/LICENSE-leaflet).

---

## 日本語

[OwnTracks Recorder](https://github.com/owntracks/recorder) の位置履歴を、Google マップのタイムライン風の日別表示（滞在、移動手段で色分けした移動、地図）で見られるサイドバーパネルを追加する Home Assistant カスタム統合です。

- UI の文言は日本語です。
- 逆ジオコーディング（地域名）は日本国内のみ対応しています。
- 過去分は Google マップのタイムラインのエクスポートから滞在／移動を使えます。それ以降は記録された点列から推定します。

### 必要なもの

- Home Assistant 2026.3 以降
- Home Assistant から HTTP で認証なしに接続できる OwnTracks Recorder

### インストール

#### Marketplace（Home Assistant 2026.11 以降）

1. **設定 → Marketplace** を開き、**Add from link** を選びます。
2. `https://github.com/tsukuyomi-luna/ha-location-timeline` を入力して追加します（種類は **Integration**）。
3. 一覧の **Location Timeline** を開いて **Install** を選びます。
4. 下記の YAML 設定を `configuration.yaml` に追加します。
5. Home Assistant を再起動します。

#### HACS（それより前の Home Assistant）

1. HACS で ⋮ → **Custom repositories** を開きます。
2. `https://github.com/tsukuyomi-luna/ha-location-timeline` を種類 **Integration** で追加します。
3. HACS で **Location Timeline** を探してダウンロードします。
4. 下記の YAML 設定を `configuration.yaml` に追加します。
5. Home Assistant を再起動します。

#### 手動

1. `custom_components/location_timeline/` を Home Assistant の `/config/custom_components/` にコピーします。
2. 下記の YAML 設定を `configuration.yaml` に追加します。
3. Home Assistant を再起動します。

### 設定

```yaml
location_timeline:
  recorder_url: http://recorder.local:8083  # OwnTracks Recorder (認証なし)
  user: me
  device: phone
  segments_file: location_timeline/google_segments.json  # 任意。/config からの相対パスか絶対パス
  towns_db: location_timeline/towns.sqlite               # 任意
  places_file: location_timeline/places.json             # 任意
  sidebar_title: タイムライン   # 既定値
  sidebar_icon: mdi:map-clock  # 既定値
  require_admin: true          # 既定値。false なら管理者以外も閲覧可
```

指定したファイルが存在しなくても起動します（警告ログのみ）。sidecar と places は更新時刻が変わると自動で読み直します。

場所名は Home Assistant の zone → `places.json` → Google の `semanticType`（Home→自宅、Work→職場）の順で決めます。地域名（例: 千代田区丸の内一丁目）は `towns.sqlite` から引きます。

### データファイル

これらのデータファイルはこのリポジトリには**含まれていません**。自分の位置データそのもの、またはそこから作ったものなので、絶対にコミットしないでください。よくあるファイル名は `.gitignore` で除外しています。

スクリプトは Python 標準ライブラリだけで動きます（Python 3.12 以降）。

#### `google_segments.json`（任意）

Google マップのタイムラインを端末からエクスポートした `Timeline.json` から作ります。

```sh
python3 scripts/build_google_sidecar.py Timeline.json /config/location_timeline/google_segments.json
```

#### `towns.sqlite`（任意、逆ジオコーディング用）

<https://geolonia.github.io/japanese-addresses/latest.csv> から `latest.csv` をダウンロードして実行します。

```sh
python3 scripts/build_towns_db.py latest.csv /config/location_timeline/towns.sqlite
```

CSV は [Geolonia 住所データ](https://github.com/geolonia/japanese-addresses) です。データのライセンスは CC BY 4.0（表示:「Geolonia 住所データ」）、同リポジトリの生成スクリプトは MIT です。このデータセットは上流で更新が終了しています。

#### `places.json`（任意）

名前付き地点です。Home Assistant の zone より優先度が低くなります。`radius` の単位はメートルです。

```json
[{"name": "ジム", "lat": 35.0, "lon": 139.0, "radius": 100}]
```

### HTTP API

どちらも Home Assistant の認証が必要です。`require_admin: true` のときは管理者以外に 403 を返します。

- `GET /api/location_timeline/day?date=YYYY-MM-DD`: その日（Home Assistant のタイムゾーンの暦日）のタイムライン。`date` を省略すると今日。不正な日付は 400、Recorder への接続失敗は 502（`{"error": "..."}`）。
- `GET /api/location_timeline/range`: `{"first": "2026-01-01" | null, "last": "<今日>"}`。`first` は sidecar の最初の区間の日付。

### プライバシー

- 座標がネットワークの外に出ることはありません。Home Assistant が通信するのは自分の Recorder だけです。
- 外部への通信は、ブラウザから OpenStreetMap（`tile.openstreetmap.org`）への地図タイルの取得だけです。表示中の地図範囲（タイル番号）とブラウザの IP アドレスが OSM のタイルサーバーに伝わります。
- Leaflet は同梱しているため、ほかの CDN は使いません。
- データファイル（sidecar、`places.json`、`Timeline.json`、`towns.sqlite`）を `/config/www/` に置かないでください。そこのファイルは `/local/` で認証なしに配信されます。`/config/location_timeline/` などに置いてください。この統合は認証付きの API 経由でのみデータを返します。

### ライセンス

MIT。[LICENSE](LICENSE) を参照してください。

同梱の [Leaflet](https://leafletjs.com/) は BSD-2-Clause です。[`custom_components/location_timeline/frontend/vendor/LICENSE-leaflet`](custom_components/location_timeline/frontend/vendor/LICENSE-leaflet) を参照してください。
