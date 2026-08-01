# soundcraft

[English](README.md)

テキストから音楽を生成する — デスクトップアプリ / ブラウザ GUI / CLI /
TouchDesigner などから叩けるローカル HTTP API。

```
テキスト →（任意）ローカル LLM で整形 → 選んだバックエンド → 音声ファイル
```

<p align="center">
  <img src="docs/demo/gui.jpg" alt="soundcraft — プロンプトから生成結果まで" width="900" />
</p>

## バックエンド

soundcraft は特定のモデルに縛られません。作り方に合うものを選べば OK で、
必要なのは 1 つだけ。生成のたびに切り替えられます。

| バックエンド | 実行場所 | 必要なもの | 向いている用途 |
|-------------|---------|-----------|--------------|
| **ComfyUI** | 自分の GPU | 起動中の ComfyUI + ワークフロー | ComfyUI が対応するもの全部（ACE-Step / Stable Audio / MusicGen …）。モデル追加にコード変更は不要 |
| **Local** | 自分の CPU/GPU | `[local]` extra（PyTorch） | オフラインで動き続ける必要があるインスタレーション。課金も制限もなし |
| **Replicate** | ホスト型 | API トークン | GPU がない、まず試したい |
| **Hugging Face** | ホスト型 | read トークン | 無料枠あり。最短で音を出せる |
| **Lyria** | ホスト型 | Gemini キー + `[lyria]` extra | メロディック・トーナルな曲寄りの素材 |

会期中ずっと回すような作品（ギャラリー展示、ライブ）では **ComfyUI** か
**Local** を推奨します。ネットワーク・レート制限・課金がどれも効きません。

`soundcraft providers` で、各バックエンドに何が足りないかを一覧できます。

## インストール

### デスクトップアプリ

[Releases](https://github.com/naotochan/soundcraft/releases) から自分の
プラットフォーム向けをダウンロードして解凍・実行するだけです。

ビルドは **未署名** です:

- **macOS** — `Soundcraft.app` を右クリック → **開く** → **開く**。初回だけ
- **Windows** — 初回起動時に SmartScreen が出ます: **詳細情報** → **実行**
- **Linux** — `./Soundcraft/Soundcraft`

### ソースから

```bash
git clone https://github.com/naotochan/soundcraft.git
cd soundcraft

uv venv && source .venv/bin/activate
uv pip install -e "."            # CLI・API サーバー・ComfyUI ブリッジ
uv pip install -e ".[app]"       # + デスクトップ窓
uv pip install -e ".[local]"     # + ローカル MusicGen（PyTorch・大きい）
uv pip install -e ".[lyria]"     # + Google Lyria

soundcraft doctor                # 何が設定済みで何が足りないか
```

コアのインストールは意図的に小さく保っています（PyTorch も GUI ツールキットも
含まない）。ヘッドレスサーバーにそのまま入れられます。

## バックエンドの設定

アプリの Settings、またはコマンドラインから:

```bash
# ComfyUI — 詳細は docs/comfyui.md
soundcraft config set COMFYUI_URL http://127.0.0.1:8188
soundcraft config set COMFYUI_WORKFLOW my-workflow.json

# ホスト型
soundcraft config set REPLICATE_API_TOKEN r8_…
soundcraft config set HF_API_TOKEN hf_…
soundcraft config set GEMINI_API_KEY AIza…

soundcraft config list
soundcraft doctor
```

設定はユーザーごとに保存されます（macOS:
`~/Library/Application Support/soundcraft/.env`、Linux:
`~/.config/soundcraft/.env`、Windows: `%APPDATA%\soundcraft\.env`）。
プロジェクト直下の `.env` も読みます — `.env.example` を参照。

## 起動

| 用途 | コマンド |
|------|----------|
| デスクトップ窓 | `soundcraft app` |
| ブラウザ GUI | `soundcraft gui` |
| API のみ | `soundcraft serve` |
| ワンショット | `soundcraft "暗い、鼓動、インスタレーション"` |

## CLI

```bash
soundcraft "dark ambient drone, heavy reverb" --raw
soundcraft "glitch, metallic" -b comfyui -p duration=45 -p seed=1234
soundcraft "bright pop hook" -b lyria -n 3
soundcraft providers -v          # 全バックエンドとそのパラメータ
```

| フラグ | 説明 | デフォルト |
|--------|------|-----------|
| `-b` | バックエンド id | 設定済みの先頭 |
| `-p` | `name=value` のバックエンド固有パラメータ（複数可） | プロバイダの既定値 |
| `-d` | `-p duration=…` の短縮形 | — |
| `-m` | `-p model=…` の短縮形 | — |
| `-n` | バリエーション数 | `1` |
| `-o` | 出力ディレクトリ | `output/`、アプリでは `~/Documents/soundcraft/output` |
| `--raw` | LLM によるプロンプト整形をスキップ | off |

パラメータがバックエンドごとに違うのは、モデル自体が違うからです。
`soundcraft providers -v` で、選んだバックエンドが受け付ける項目を確認できます。

## ローカル API

GUI / デスクトップアプリと同じプロセス。デフォルト `http://127.0.0.1:8765`

| メソッド | パス | 説明 |
|----------|------|------|
| `GET` | `/health` | 生存確認（常に認証不要） |
| `GET` | `/providers` | バックエンド・パラメータ・準備状態 |
| `GET` `PUT` | `/settings` | 設定の読み書き |
| `POST` | `/generate` | 同期生成 |
| `POST` | `/jobs` | 非同期生成（TouchDesigner 向き） |
| `GET` | `/jobs/{id}` | ジョブ確認 |
| `GET` `DELETE` | `/library` | 生成済みトラックの一覧・削除 |
| `GET` | `/media?path=` | ファイルのストリーム |
| `POST` | `/refine` | プロンプト整形のプレビュー |

```bash
curl -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"暗い、鼓動","backend":"comfyui","params":{"duration":30},"count":1}'
```

レスポンスの `files` は絶対パスです（TouchDesigner なら
`Audio File In CHOP` へ）。

### localhost の外に公開する

トークンなしで loopback 以外にバインドしようとするとサーバーは起動を拒否します:

```bash
soundcraft config set SOUNDCRAFT_API_TOKEN "$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
soundcraft serve --host 0.0.0.0
```

クライアントは `Authorization: Bearer <token>` を送ります。別ホストの
ブラウザページから叩く場合は `SOUNDCRAFT_CORS_ORIGINS` も設定してください。

## 出力

```
~/Documents/soundcraft/output/…   # デスクトップアプリ
./output/…                        # CLI / プロジェクトからの serve
```

各音声ファイルには、生成時のプロンプトと設定を記録した JSON サイドカーが
並んで書かれます。Library はこれを読んでいます。保存先を変えるには
`SOUNDCRAFT_OUTPUT_DIR` を設定してください。

## 開発

```bash
uv pip install -e ".[dev,app,lyria]"
pytest
ruff check src tests
python scripts/build_app.py       # このプラットフォーム向けのデスクトップバンドル
```

バックエンドの追加は `src/soundcraft/providers/` にファイルを 1 つ置くだけです。
パラメータと設定を宣言して `generate()` を実装すれば、CLI・API・GUI が自動的に
拾います。ComfyUI ブリッジがワークフローをどう扱うかは `docs/comfyui.md` を参照。

## 必要なもの

- Python 3.10+（またはデスクトップビルド）
- 設定済みのバックエンドが最低 1 つ — `soundcraft doctor` が教えてくれます
- プロンプト整形用の LM Studio 等 OpenAI 互換エンドポイント（任意）
