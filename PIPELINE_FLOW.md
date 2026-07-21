# 動画生成パイプラインの現状フロー（2026-07-19時点）

`video-maker` スキルが台本テーマ受け取りから投稿まで一気通貫で進める。以下はコードの実装（`src/pipeline.py` / `src/image_dashboard.py` / `.claude/skills/video-maker/SKILL.md`）を実際に読んで起こした現状フロー。

## 全体フロー

```mermaid
flowchart TD
    A[テーマ受け取り] --> B["STEP2: script-writerスキルで台本生成\nscripts/NN_slug.json"]
    B --> C{ユーザーレビュー\nOK?}
    C -- 修正 --> B
    C -- OK --> D

    subgraph STEP2_5["STEP2.5: 画像自動選定（ダッシュボードなし）"]
        D["image_dashboard.py --fetch-only"] --> D1["assets/materials/index.json\nライブラリマッチング"]
        D --> D2["WebScrapeProvider\nDuckDuckGo即時検索"]
        D1 --> D3["manifest.json +\ncontact_s{NN}.jpg生成"]
        D2 --> D3
        D3 --> D4["Claudeがコンタクトシート+\nmanifestテキストを見て1シーン1枚選定"]
        D4 --> D5["output/stem/image_selections.json 書き出し"]
    end

    D5 --> E

    subgraph STEP3["STEP3: TikTok版生成（メイン）"]
        E["pipeline.py --platform tiktok\n--selections image_selections.json"] --> E1["シーンごとにTTS合成(gTTS,キャッシュ)"]
        E1 --> E2["選定画像/動画をコピー\n(取得は一切しない)"]
        E2 --> E3["BGM bed生成(rotate)"]
        E3 --> E4["build_video():\nKenBurns+字幕+タイトル帯+SFX+結合+ffmpeg"]
        E4 --> E5["サムネイル生成\nyoutube_meta.txt生成\ncredits.json書き出し"]
        E5 --> E6["TODO.md自動更新(②列・状態)"]
    end

    E6 --> F{STEP4: ユーザーが\n完成動画を確認}
    F -- 特定シーンの画像が合わない --> G["該当シーンだけ\nimage_selections.json編集"]
    G --> H["pipeline.py --platform tiktok\nで1回だけ再生成"]
    H --> F
    F -- OK --> I

    subgraph STEP5["STEP5: YouTube版生成"]
        I["pipeline.py --platform youtube\n--selections image_selections.json"] --> I1["60秒以下になるまで\nシーン間引き"]
        I1 --> I2["{count}をシーン数に応じ解決\n→ narration/タイトル置換\n変わったら該当シーンTTS再生成"]
        I2 --> I3["build_video() 同上"]
        I3 --> I4["TODO.md自動更新(③列・状態)"]
    end

    I4 --> J["📱 TikTok手動投稿\n(本番審査待ちのため)"]
    I4 --> K["upload.py --schedule\nYouTube予約投稿\nTODO.md自動更新(📅列)"]
```

## 差し替えループの詳細（STEP4）

ダッシュボードでの事前確認を廃止（2026-07-18〜）したため、画像の良し悪しは**完成動画を見て**判断する。

```mermaid
sequenceDiagram
    participant U as ユーザー
    participant C as Claude
    participant P as pipeline.py

    C->>P: --platform tiktok 生成
    P-->>U: final_output_tiktok.mp4
    U->>C: 気になるシーンをまとめて指摘（例:「3と6」）
    C->>C: manifest.jsonの別候補を確認・選定
    C->>C: image_selections.jsonの該当シーンのみ書き換え
    C->>P: --platform tiktok で1回だけ再生成
    P-->>U: 更新版
    U->>C: OK
    C->>P: --platform youtube 生成
```

---

## 使われていない／死んでいたコードパス

コードを実読して確認し、**2026-07-19に削除済み**:

| 項目 | 場所 | 対応 |
|---|---|---|
| `image_dashboard.py`の確認ダッシュボード一式（`generate_html`/`run_dashboard`/`_Handler`/`selections_to_preselect`/`log_selection_diffs`、`--preselect`/`--refresh` CLIフラグ） | `src/image_dashboard.py` | ✅ 削除済み。`fetch_only()`（候補取得＋コンタクトシート生成）のみ残す |
| `get_image_provider()` ファクトリ関数 | `src/images.py` | ✅ 削除済み（呼び出し元が存在しなかった） |
| `PinterestImageProvider`クラス | `src/images.py` | ✅ 削除済み（`get_image_provider()`経由でしか呼ばれず、そちらも死んでいたため道連れで削除） |
| `load_manifest()` | `src/image_dashboard.py` | ✅ 削除済み（`run_dashboard`削除で呼び出し元消滅） |

残置（削除しなかったもの・理由）:

| 項目 | 場所 | 理由 |
|---|---|---|
| 台本JSONの`meta.image_provider`フィールド | 全55台本 | データフィールドであり「処理」ではない。55ファイル一括編集のコストに対し実害がないため見送り。今後 script-writer スキルが新規に書かないようにするのは別途検討 |
| `StockImageProvider`・`WebScrapeProvider` | `src/images.py` | `material-collector`スキル（`collect_materials.py`）が実際に使用中 |
