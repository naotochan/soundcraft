# Session Log — soundcraft

## プロジェクト概要
フィンガードラム・ループミックス・インスタレーション・メディアアート向けインストゥルメンタル音楽の自動生成ワークフロー。
テキスト入力 → MusicGen（Replicate API） → WAV保存。
将来的にClaude APIプロンプト整形、TouchDesigner / SuperCollider連携を想定。

- **技術スタック**: Python, Replicate API, MusicGen (Meta/AudioCraft)
- **環境**: Mac（GPUなし）
- **出力**: WAV素材

---

## 2026-03-26 13:36

### 完了したこと
- プロジェクト基盤構築（pyproject.toml, .gitignore, ディレクトリ構成）
- HF Inference API廃止を確認 → Replicate API（REST直接呼び出し）に切り替え
- MusicGen CLI実装完了（generate.py, cli.py, config.py）
- 初回生成テスト成功: "ambient electronic loop, dark atmosphere" → WAV 500KB, 16bit mono 32kHz
- モデル選択肢: melody-large, stereo-melody-large, large, stereo-large

### 次のステップ
- git init + 初期コミット + ブランチ運用開始
- Claude APIプロンプト整形機能の追加
- TouchDesignerでの音源読み込みテスト

### 気づき・メモ
- HF Inference APIは2026年時点で廃止済み（410 Gone）、text-to-audioはInference Providersでも未サポート
- Replicate Python SDK (v1.0.7) で402エラーが出るがREST APIでは正常動作 → REST直接呼び出しで解決
- musicgen model_versionが "melody" → "melody-large" 等に変更されていた
