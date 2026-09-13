# 自動投稿システム セットアップ手順（社長がやる部分）

これは「Publerの自前版」。各SNSの公式APIで投稿し、GitHub Actions（無料）が15分ごとに自動実行するので、**PCが消えていても毎日投稿されます**。費用0円。

> ⚠️ **鍵（APIキー・トークン）は絶対にチャットに貼らない・AIに見せない。** GitHubの「Secrets」に直接入れます。AIはコードと手順だけ作り、鍵には触りません。

## 0. 必要なもの
- GitHubアカウント（無料）
- X（旧Twitter）のアカウント → 開発者登録（無料枠）
- Threadsのアカウント → Meta for Developers（無料）

## 1. GitHubにこのフォルダを置く（1回だけ）
1. https://github.com で無料アカウント作成
2. 「New repository」→ 名前 `autopost`・**Public** で作成（画像を公開URLで参照するため。鍵はSecretsに入れるので安全）
3. この `autopost` フォルダの中身を全部アップロード（Webの「Add file → Upload files」でOK）
   - `post.py` / `requirements.txt` / `schedule.json` / `.github/workflows/autopost.yml` / `images/`（画像フォルダごと）
4. リポジトリの「Actions」タブ → 有効化

## 2. X の鍵を取る（無料枠で投稿できる）
1. https://developer.x.com → ログイン → **Free** プランで登録
2. Project/App を作成 → **User authentication settings** を「**Read and Write**」に設定（Type: Web App / Callback は `https://example.com` でOK）
3. 「Keys and tokens」で以下を**生成**（Read and Write に変えた後に Access Token を作り直すこと）
   - API Key → Secretsに `X_API_KEY`
   - API Key Secret → `X_API_SECRET`
   - Access Token → `X_ACCESS_TOKEN`
   - Access Token Secret → `X_ACCESS_SECRET`

## 3. Threads の鍵を取る
1. https://developers.facebook.com → 「アプリを作成」→ 用途「その他」→ タイプ「ビジネス」
2. アプリに **Threads API** を追加
3. 「ユースケース → Threads → 設定」で自分のThreadsアカウントを**テスターに追加**し、Threadsアプリ側で承認
4. 「Threads API → ユーザートークン生成ツール」でトークン生成 → **長期トークン**に交換（60日有効。切れたら再発行）
   - アクセストークン → Secretsに `THREADS_ACCESS_TOKEN`
   - ユーザーIDは不要（システムが "me" を使う）。`THREADS_USER_ID` は登録しなくてOK

## 4. GitHub Secrets に登録
リポジトリ → Settings → Secrets and variables → Actions → 「New repository secret」で上の6つ＋下の1つを登録。
- `IMAGE_BASE_URL` → `https://raw.githubusercontent.com/<あなたのGitHubユーザー名>/autopost/main/images`（Threadsの画像投稿に必要）

## 5. 動作確認
Actions タブ → `autopost` → 「Run workflow」で手動実行 → ログに `nothing due` か投稿IDが出ればOK。

## 運用（週1のPC起動日）
- 新しい投稿は `schedule.json` に追記（AIが作る）→ GitHubにアップロード（上書き）
- あとは放置。予定時刻を過ぎたら自動投稿。投稿済みは `posted.json` に記録される。

## 今後の拡張（コウ）
- Instagram（画像付き）：プロアカウント＋Facebookページ連携＋Meta Graph API
- TikTok：Content Posting API は審査が要るため、当面はTikTok公式の「予約投稿」を使う
- Threadsトークンの自動更新

## テストだけしたい時
PCで `DRY_RUN=1 python post.py` → 投稿せずに「何を出すか」だけ表示（記録もしない）。

## SNS別の出し分け方針（みや）
- **X / Threads＝文字メイン**：同じ本文でOK（`text_threads` で長め・会話調に変えても可）。週9本に画像カードを添付して目を止める
- **Instagram＝画像/動画メイン**：カード画像（`images/`）＋短いキャプション。リールは動画①など
- **TikTok＝動画のみ**：カード動画（CapCut）。当面は公式の予約投稿を使用
