# soundcraft

[English](README.md)

テキストプロンプトからインストゥルメンタル音楽を生成する CLI ツール（MusicGen / Lyria3 対応）。

テキスト入力（日本語/英語） → LLM プロンプト整形 → MusicGen or Lyria3 → 音声ファイル

## セットアップ

```bash
uv venv
uv pip install -e .
source .venv/bin/activate
```

`.env` を作成:

```
REPLICATE_API_TOKEN=your_token_here
GEMINI_API_KEY=your_gemini_api_key_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

## 使い方

```bash
# 基本（日本語入力OK）
soundcraft "暗い、鼓動、インスタレーション"

# LLM整形をスキップ
soundcraft "dark ambient drone, heavy reverb" --raw

# Lyria3バックエンドを使用
soundcraft "energetic pop beat, bright" -b lyria3

# オプション指定
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

### オプション

| フラグ | 説明 | デフォルト |
|--------|------|-----------|
| `-b` | バックエンド: `musicgen`, `lyria3` | `musicgen` |
| `-m` | モデル（MusicGen）: `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | 長さ・秒（MusicGen） | `30` |
| `-n` | バリエーション数 | `3` |
| `-o` | 出力ディレクトリ | `output/` |
| `--raw` | LLM プロンプト整形をスキップ | off |

## バックエンド

| バックエンド | API | 出力 | 得意分野 |
|-------------|-----|------|---------|
| MusicGen | Replicate | WAV | アンビエント、実験的、ダークなテクスチャ |
| Lyria3 | Gemini | MP3（30秒クリップ） | ポップ、明るい、メロディック |

## 出力

ファイル名はプロンプトの先頭4単語 + 連番:

```
output/dark_ambient_drone_with_001.wav   # MusicGen
output/energetic_pop_beat_bright_001.mp3 # Lyria3
```

## アーキテクチャ

```
テキスト入力
  ↓
LM Studio（プロンプト整形、任意）
  ↓
MusicGen（Replicate API） → WAV
  or
Lyria3（Gemini API）      → MP3
  ↓
音声ファイルを output/ に保存
```

## 必要なもの

- Python 3.10+ / [uv](https://docs.astral.sh/uv/)
- [Replicate API トークン](https://replicate.com/account/api-tokens)（MusicGen用）
- [Gemini API キー](https://aistudio.google.com/apikey)（Lyria3用）
- LM Studio（任意、プロンプト整形用）
