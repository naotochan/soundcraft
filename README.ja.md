# soundcraft

[English](README.md)

テキストプロンプトからインストゥルメンタル音楽を生成する MusicGen CLI ツール。

テキスト入力（日本語/英語） → LLM プロンプト整形 → MusicGen（Replicate API） → WAV ファイル

## セットアップ

```bash
pip install -e .
```

`.env` を作成:

```
REPLICATE_API_TOKEN=your_token_here
LM_STUDIO_URL=http://localhost:1234
LM_STUDIO_MODEL=liquid/lfm2-24b-a2b
```

## 使い方

```bash
# 基本（日本語入力OK）
soundcraft "暗い、鼓動、インスタレーション"

# LLM整形をスキップ
soundcraft "dark ambient drone, heavy reverb" --raw

# オプション指定
soundcraft "glitch, metallic" -m stereo-melody-large -d 15 -n 5
```

### オプション

| フラグ | 説明 | デフォルト |
|--------|------|-----------|
| `-m` | モデル: `melody-large`, `stereo-melody-large`, `large`, `stereo-large` | `melody-large` |
| `-d` | 長さ（秒） | `30` |
| `-n` | バリエーション数 | `3` |
| `-o` | 出力ディレクトリ | `output/` |
| `--raw` | LLM プロンプト整形をスキップ | off |

## 出力

ファイル名はプロンプトの先頭4単語 + 連番:

```
output/dark_ambient_drone_with_001.wav
output/dark_ambient_drone_with_002.wav
output/dark_ambient_drone_with_003.wav
```

## アーキテクチャ

```
テキスト入力
  ↓
LM Studio（プロンプト整形、任意）
  ↓
Replicate API（MusicGen）
  ↓
WAV ファイルを output/ に保存
```

## 必要なもの

- Python 3.10+
- [Replicate API トークン](https://replicate.com/account/api-tokens)
- LM Studio（任意、プロンプト整形用）
