# soundcraft

[English](README.md)

テキストプロンプトからインストゥルメンタル音楽を生成する CLI / GUI / ローカル API（MusicGen / Lyria3）。

```
テキスト →（任意）LM Studio 整形 → MusicGen or Lyria3 → 音声ファイル
```

配布は **ソース正**（クローンして実行）。macOS の `.app` パッケージはありません。ブラウザ GUI がアプリ UI です。

## クイックスタート

```bash
git clone https://github.com/naotochan/soundcraft.git
cd soundcraft

uv venv
uv pip install -e .
source .venv/bin/activate

cp .env.example .env
# .env を編集 — 少なくともどちらか一方:
#   REPLICATE_API_TOKEN  (MusicGen)
#   GEMINI_API_KEY       (Lyria3)

soundcraft gui
```

ローカルサーバーが立ち上がり、ブラウザで `http://127.0.0.1:8765/` が開きます。

| 用途 | コマンド |
|------|----------|
| GUI | `soundcraft gui` |
| API のみ（TouchDesigner など） | `soundcraft serve` |
| ワンショット CLI | `soundcraft "暗い、鼓動、インスタレーション"` |

## `.env`

```
REPLICATE_API_TOKEN=your_token_here
GEMINI_API_KEY=your_gemini_api_key_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

LM Studio は任意（プロンプト整形）。不要なら `--raw`。

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
| `-m` | モデル（MusicGen）: `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | 長さ・秒（MusicGen） | `30` |
| `-n` | バリエーション数 | `3` |
| `-o` | 出力ディレクトリ | `output/` |
| `--raw` | LLM プロンプト整形をスキップ | off |

## ローカル API

GUI と同じプロセス（`serve` / `gui`）。デフォルト: `http://127.0.0.1:8765`

| メソッド | パス | 説明 |
|----------|------|------|
| `GET` | `/` | ブラウザ GUI |
| `GET` | `/health` | 生存確認 |
| `POST` | `/generate` | 同期生成 |
| `POST` | `/jobs` | 非同期生成（TD 向け） |
| `GET` | `/jobs/{id}` | ジョブ確認 |
| `GET` | `/media?path=` | `output/` 配下の再生用ストリーム |

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
output/dark_ambient_drone_with_001.wav   # MusicGen
output/energetic_pop_beat_bright_001.mp3 # Lyria3
```

## 必要なもの

- Python 3.10+ / [uv](https://docs.astral.sh/uv/)
- [Replicate API トークン](https://replicate.com/account/api-tokens)（MusicGen）
- [Gemini API キー](https://aistudio.google.com/apikey)（Lyria3）
- LM Studio（任意）
