# 検証記録

作業日：2026-11-03（Asia/Tokyo）。公開と実機試験の結果は完了時にこの記録へ追記します。

初期結果：Python 3.12で外部API不要のpytest 68件成功。localhostソケットを使う1件は実行環境のサンドボックス制約により通常実行では失敗し、ソケット許可のある実行で全件成功。

既存pyenv 3.12.13は、見つからないHomebrew OpenSSL 3の動的ライブラリに依存していたため、HTTPSを使う配布試験にはHomebrew Python 3.14の専用仮想環境を使用。既存pyenvやシステムのライブラリは変更していません。

未検証を成功扱いにしない項目：本番Sarashina API認証・実生成、実際の異なるバージョン間brew upgrade、Intel実機、スリープ復帰・翌朝8時の自動実行。追加の実行結果は下に記録します。

## ローカル実機検証

- Apple Silicon / macOS上のHomebrew Python 3.14でpytest **74件成功**。ruff成功。
- 実在するローカルsdistから`brew install --build-from-source`成功。`brew test`と`brew audit`成功。FormulaのRuby構文検査成功。
- APIキーなしでCLI起動、initの冪等性、同梱テンプレート、DB保持、RSS出力、doctor --offlineを確認。
- 独自home・ポート18080でバッチ/HTTPのLaunchAgentを実際にinstall/start/statusし、launchctl kickstartでバッチを実行。未処理0件でAPI呼び出し0回。
- 実プロセスの待受が`127.0.0.1:18080`だけであることをlsofで確認。doctorのHTTP検査もok。
- テスト用LaunchAgentはstop/uninstallし、登録解除済み。データは`.local/e2e`に保持。
- Sarashina本番キーは環境変数・キーチェーンともに未設定。実APIでの認証・記事生成は未検証。
- NetNewsWireは起動を確認したが、既存アカウント設定ダイアログが開かれていたため、その操作を妨げず購読・本文の目視確認は未実施。RSS XMLとlocalhost HTTPの試験は成功。

- 公式Nature RSSの実フィードから2件を収集し、原題・DOI・抄録を取得。再収集は新着0件・重複2件、API呼び出し0回。
- ローカル試験Formulaのrevisionを上げ、実際の`brew upgrade`（1.0.0→1.0.0_1）成功。設定2ファイル・記事DB・RSSのSHA-256が全て一致。
- `brew uninstall`と残存旧版Cellarの削除後も上記SHA-256が全て一致。異なるアプリリリース間・将来のスキーマ移行を伴うupgradeは未検証。
- 最初のGitHub ActionsではmacOS/Linux × Python 3.11/3.14の4構成、wheelの別環境インストール、macOS Homebrewインストール・audit・test・reinstall/uninstall保持確認が全て成功。最新ソースの結果はActionsで確認する。

- 設定ファイルが壊れていてもservice stop/status/uninstallで復旧できることを追加テスト。最新のローカルテストは74件成功。

## 公開済み配布物

- アプリタグ：`v1.0.0`（実装コミット `8cf9dcd7f2a50917b8ab532e1cc4f91a9f1fca98`）。
- [GitHub Release](https://github.com/KentoYana/LiteratureDigest/releases/tag/v1.0.0) を公開済み。sdist、wheel、SHA256SUMSを配布。
- sdist SHA-256：`45dde31fae3f4981e2f1b8a2b06e0fbb9f9d06533119fb28089a1a42bca275fc`。公開assetを取得して実測し、GitHub公表digestと一致。
- [Release Actions](https://github.com/KentoYana/LiteratureDigest/actions/runs/41653610936) 成功。JSON SchemaやAPIクライアントもモックで検証した74件を実行。生成Formulaとローカル再生成Formulaが完全一致。
- [アプリCI](https://github.com/KentoYana/LiteratureDigest/actions/runs/41653579346) は最終実装で全5ジョブ成功。macOS/Linux × Python 3.11/3.14、wheel別環境導入、macOS Homebrewインストール・audit・test・再インストール/削除時保持。
- Tap `KentoYana/homebrew-tap`の`0a7b80822e711812ce755d5b564bd9edccd96b7c`へFormula・README・専用macOS workflowを反映済み。他のFormulaは変更していない。
- 実機で公開先の`brew install --build-from-source KentoYana/tap/literature-digest`が成功。ローカルfile URLではなく、GitHub Releaseの固定アーカイブを使用。
- クロスリポジトリ自動更新用の`TAP_GITHUB_TOKEN`は未設定。初回Tap反映には既存gh認証を使用した。次回以降は同Secretを設定するか、生成Formulaを公開手順に従って手動で反映する。

本番キー・購読先のユーザー設定とNetNewsWireでの目視確認は残るため、すべての完成条件を実機で検証済みとは扱わない。

- 公開Tap版で`brew test`、`brew audit`、`--version`、`init --copy-prompt`、`doctor --offline`が成功。既存テストDBの記事がそのまま読め、設定・DB・RSSの全ハッシュも一致。
- Tap CIの初回はHomebrew 7の信頼登録要件によりauditで失敗。Tap全体ではなく対象Formulaだけを信頼する工程を追加した`5c9f0e103cffa5e75ee1e88401fe537fbdd4209d`で修正。
- [修正後Tap CI](https://github.com/KentoYana/homebrew-tap/actions/runs/41654578144)の全工程が成功。実際の公開アーカイブでaudit・install・brew test・CLI・doctorを検証。
- 不要になった試験Tapは登録解除。実機には公開TapのLiteratureDigest 1.0.0をインストールした状態で残し、定期実行・HTTPサービスは登録していない。標準ユーザーディレクトリの初期設定は利用者の`init`で行う。
