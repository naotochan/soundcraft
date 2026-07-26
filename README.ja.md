# soundcraft

[English](README.md)

テキストプロンプトからインストゥルメンタル音楽を生成する CLI / デスクトップアプリ / GUI / ローカル API（MusicGen / Lyria3）。

```
テキスト →（任意）LM Studio 整形 → MusicGen or Lyria3 → 音声ファイル
```

<p align="center">
  <img src="docs/demo/gui.jpg" alt="soundcraft — プロンプトから生成結果まで" width="900" />
</p>

## みんな向け（macOS アプリ）

1. [Releases](https://github.com/naotochan/soundcraft/releases) から **Soundcraft-macos.zip** をダウンロード
2. 解凍して `Soundcraft.app` をアプリケーションフォルダなどへ移動
3. **初回だけ**（未公証ビルド）: Finder で `Soundcraft.app` を **右クリック** → **開く** → ダイアログでもう一度 **開く**  
   （Gatekeeper が未知の開発元を止めるため。一度通せば以後はダブルクリックで OK）
4. アプリ内 **Settings** で API キーを入力（どちらか一方でも可）:
   - MusicGen → [Replicate トークン](https://replicate.com/account/api-tokens)
   - Lyria3 → [Gemini API キー](https://aistudio.google.com/apikey)
5. 生成する — 出力は `~/Documents/soundcraft/output/`

キーの保存先: `~/Library/Application Support/soundcraft/.env`（この Mac のみ）

## 開発者向け（ソース）

```bash
git clone https://github.com/naotochan/soundcraft.git
cd soundcraft

uv venv
uv pip install -e .
source .venv/bin/activate

cp .env.example .env
# .env を編集 — または GUI / デスクトップアプリの Settings

soundcraft app          # デスクトップ窓（pywebview）
soundcraft gui          # ブラウザ UI
soundcraft serve        # API のみ（TouchDesigner など）
soundcraft "暗い、鼓動、インスタレーション"
```

| 用途 | コマンド |
|------|----------|
| デスクトップ窓 | `soundcraft app` |
| ブラウザ GUI | `soundcraft gui` |
| API のみ | `soundcraft serve` |
| ワンショット CLI | `soundcraft "…"` |

### macOS `.app` のビルド

```bash
uv pip install -e ".[build]"
chmod +x scripts/build_macos_app.sh
./scripts/build_macos_app.sh
# → dist/Soundcraft.app と dist/Soundcraft-macos.zip
```

zip は **未公証**です。利用者には初回の「右クリック → 開く」を案内してください。

## `.env`（開発者）

```
REPLICATE_API_TOKEN=your_token_here
GEMINI_API_KEY=your_gemini_api_key_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

デスクトップアプリモードでは Settings が Application Support に書き込みます。LM Studio は任意。

## CLI

```bash
soundcraft "暗い、鼓動、インスタレーション"
soundcraft "dark ambient drone, heavy reverb" --raw
soundcraft "energetic pop beat, bright" -b lyria3
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

| フラグ | 説明 | デフォルト |
|--------|------|-----------|
| `-b` | バックエンド: `musicgen`, `lyria3` | `musicgen` |
| `-m` | モデル（MusicGen） | `melody-large` |
| `-d` | 長さ・秒（MusicGen） | `30` |
| `-n` | バリエーション数 | `3` |
| `-o` | 出力ディレクトリ | `output/`（CLI）または `~/Documents/soundcraft/output/`（アプリ） |
| `--raw` | LLM プロンプト整形をスキップ | off |

## ローカル API

GUI / デスクトップアプリと同じプロセス。デフォルト: `http://127.0.0.1:8765`

| メソッド | パス | 説明 |
|----------|------|------|
| `GET` | `/` | GUI |
| `GET` | `/health` | 生存確認 |
| `GET` | `/settings` | 設定（キーはマスク） |
| `PUT` | `/settings` | API キー保存 |
| `POST` | `/settings/open-output` | 出力フォルダを開く |
| `POST` | `/generate` | 同期生成 |
| `POST` | `/jobs` | 非同期生成（TD 向け） |
| `GET` | `/jobs/{id}` | ジョブ確認 |
| `GET` | `/media?path=` | 再生用ストリーム |

```bash
curl -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"暗い、鼓動","backend":"musicgen","count":1}'
```

レスポンスの `files` は絶対パス（TD では `Audio File In CHOP` などへ）。

## バックエンド

| バックエンド | API | 出力 | 得意分野 |
|-------------|-----|------|---------|
| MusicGen | Replicate | WAV | アンビエント、実験的、ダークなテクスチャ |
| Lyria3 | Gemini | MP3（30秒） | ポップ、明るい、メロディック |

## 出力

```
~/Documents/soundcraft/output/…   # デスクトップアプリ
./output/…                        # CLI / プロジェクトからの serve
```

## 必要なもの

- `.app` は macOS 12+（ソース実行なら Python 3.10+ / [uv](https://docs.astral.sh/uv/)）
- [Replicate API トークン](https://replicate.com/account/api-tokens)（MusicGen）
- [Gemini API キー](https://aistudio.google.com/apikey)（Lyria3）
- LM Studio（任意）
