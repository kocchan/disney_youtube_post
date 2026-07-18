---
name: comfyui-setup
description: ComfyUI(AI画像生成)のローカル環境構築状況。導入場所・モデル・起動方法・パイプライン統合状況を記録。
metadata:
  type: project
---

画像取得を「素材ライブラリ＋Web検索」からAI画像生成（ComfyUI）に置き換える構想のため、2026-07-17に`feature/comfyui-image-generation`ブランチでComfyUIの環境構築のみ実施した（`pipeline.py`/`image_dashboard.py`への統合はまだ未着手・別途相談して進める）。

**インストール場所・起動方法:**
- プロジェクト内 `326_disneyYoutube/ComfyUI/`（公式リポジトリをclone）。当初はリポジトリ外の`~/ComfyUI`に置いていたが、2026-07-17にユーザーの指示でプロジェクト内に移動した。`assets/materials/`と同様、**大容量だが`.gitignore`対象としてリポジトリ内に置く**方式（`.gitignore`に`ComfyUI/`を追加済み）。
- 専用venv: `326_disneyYoutube/ComfyUI/venv`（Python 3.12、プロジェクト本体の`.venv`とは分離）。torch 2.13.0がMPS(Apple Silicon GPU)に対応済み（`torch.backends.mps.is_available() == True`）。venv移動後も`./venv/bin/python`を直接実行する分には問題なく動作することを確認済み（`pip`等シェバン付きスクリプトは要再作成の可能性あり、未検証）。
- 起動コマンド: `cd 326_disneyYoutube/ComfyUI && ./venv/bin/python main.py --port 8189`。API疎通確認済み(`http://127.0.0.1:8189/system_stats`)。

**ポートを8189にしている理由（重要）:**
このMacには**別プロジェクト**用のComfyUIが既に存在し常用されている: `~/Downloads/328_dmmアフィリエイト漫画/ComfyUI`（ポート**8188**、アニメ系モデル`novaAnimeXL_ilV190.safetensors`使用）。当初デフォルトの8188で起動しようとしたところポート競合で自分のサーバーが起動できておらず、既存の328プロジェクト側にAPIリクエストが飛んでいたことが判明した。ユーザーの判断で**完全分離**（別ポートで並行稼働）を選択したため、本プロジェクトのComfyUIは常に`--port 8189`を明示して起動する。328プロジェクト側のファイル・設定には触れない。
**Why:** 2プロジェクトが同じMac(M2 16GB統合メモリ)上でGPUを共有する形になるため、両方のComfyUIを同時に重い処理（生成）で使うとOOM・速度低下のリスクがある点は把握しておくこと。
**How to apply:** 本プロジェクトのComfyUI操作・スクリプトは必ず`127.0.0.1:8189`を対象にする。`8188`宛のリクエストを書かない（328プロジェクトに誤爆する）。

**導入モデル:**
- `ComfyUI/models/checkpoints/sdxl_lightning_8step.safetensors`（ByteDance/SDXL-Lightning、フル単体チェックポイント、6.5GB、CheckpointLoaderSimpleでそのまま読み込める）。
- 推奨サンプラー設定: `sampler_name=euler`, `scheduler=sgm_uniform`, `cfg=1.0`, `steps=8`（Lightning系はcfg高いと破綻する）。
- 動作確認: 1024x1024生成で正常に画像が出力されることを確認済み（`comfy_setup_test_00001_.png`、汎用の遊園地夜景プロンプトでテスト、ディズニー固有名詞は使わずテスト）。

**Civitaiのディズニー系LoRAについて（重要・著作権）:**
2026-07-17時点で以下2つをローカルに配置・ComfyUIで認識済み（`ComfyUI/models/loras/`）。ユーザーが手動でCivitaiからブラウザダウンロードしたものを配置した（Civitaiが未ログインでのAPI/curlダウンロードを401で拒否するため）。
- `disney_golden_age_style_illustrious.safetensors`（228MB） + ベースモデル`ComfyUI/models/checkpoints/novaAnimeXL_ilV190.safetensors`（6.9GB、Illustrious系、別プロジェクト328_dmmアフィリエイト漫画で使っているものと同一ファイルをコピー）
- `disneyland_castle_sd15.safetensors`（151MB、SD1.5ベース）
まだ実際に生成テストはしていない（配置・認識確認まで）。
2026-07-17、ユーザーがCivitaiで「Disney Golden Age Style」（Illustrious/Fluxベース、学習タグに`SnowWhite`/`swdwarfs`/`WizardMickey`/`EvilQueen`/`BlueFairy`等**キャラクター名そのもの**が含まれる）と「Disneyland」（SD1.5ベース、シンデレラ城の意匠を再現する背景/ポーズLoRA）の2つのLoRA導入を検討した。
**Why:** これらはCLAUDE.mdの著作権の鉄則（キャラクター・城は権利が極めて強い）に真正面から抵触する。実写素材のWeb検索よりさらに踏み込み「キャラクターデザイン・城の意匠自体を学習して新規生成する」ため、収益化チャンネルでの使用はContent IDクレーム・著作権侵害リスクが高いと判断し、ユーザーと合意の上で**ローカルでの技術検証用途のみ**に限定した（チャンネル制作物には使わない）。
**How to apply:** これら2つのLoRAが`ComfyUI/models/loras/`にあっても、`pipeline.py`/`image_dashboard.py`や台本のimage_prompt設計で使う対象に含めない。もしチャンネル用に使いたいという話が出た場合は、このメモの経緯をふまえて改めてユーザーに著作権リスクを確認すること。

**img2img（実写を参照画像として使う手法）は著作権リスクが特に高いことを実証済み（2026-07-18）。**
41_pangalactic_pizzaの実際の店内写真（パン・ギャラクティック・ピザ・ポートの自動ピザ製造機、Web検索で取得）をComfyUIのLoadImage→VAEEncode→KSamplerでimg2img（SDXL Lightning、denoise 0.4/0.6/0.8の3段階）にかけて検証した。
**Why:** denoise 0.4では元写真とほぼ同一の構図（看板レイアウト・太陽系エンブレム・左右パネル配置）がAIの筆致で塗り直されただけの状態、denoise 0.8まで上げても「モニターグリッド→中央の円錐形→下部の円形エンブレム」という元写真の骨格構造が保持され続けた。テキストプロンプトのみの生成（LoRA不使用でも）とは異なり、img2img/IPAdapterは実在の著作物（パーク内装のデザイン）を直接下敷きにするため、denoiseを上げても著作権リスクは実質的に下がりきらないことが確認できた。ユーザーとの合意によりこれもローカル技術検証のみで、チャンネル制作物には使わない。
**How to apply:** 今後「Webから素材を集めてimg2img/IPAdapterで生成に使う」という提案が出た場合、テキスト記述への変換（安全）と実写を直接画像参照にする（高リスク、この検証で実証済み）は明確に区別し、後者は都度ユーザーに用途（ローカル検証か公開動画用か）を確認する。

**未着手（今後の課題）:**
- `pipeline.py`/`image_dashboard.py`への統合方法（第3の候補ソースとして追加するか、著作権リスクが特に高いシーンのみAI生成に置き換えるか）は [[feedback_video_design]] の画像選定セクションの方針とあわせて別途相談する。統合対象は著作権クリアな汎用モデル（SDXL Lightning等）のみとし、上記ディズニー系LoRAは対象外。
- ディズニー著作物（キャラクター・城等）を避けつつ雰囲気を出すプロンプト設計のノウハウは未蓄積。
- 縦型(1080x1920)生成時の設定・生成時間は未検証（テストは1024x1024正方形のみ）。
