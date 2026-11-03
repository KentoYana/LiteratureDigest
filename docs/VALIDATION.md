# 検証記録

作業日：2026-11-03（Asia/Tokyo）。公開と実機試験の結果は完了時にこの記録へ追記します。

初期結果：Python 3.12で外部API不要のpytest 68件成功。localhostソケットを使う1件は実行環境のサンドボックス制約により通常実行では失敗し、ソケット許可のある実行で全件成功。

既存pyenv 3.12.13は、見つからないHomebrew OpenSSL 3の動的ライブラリに依存していたため、HTTPSを使う配布試験にはHomebrew Python 3.14の専用仮想環境を使用。既存pyenvやシステムのライブラリは変更していません。

未検証を成功扱いにしない項目：本番Sarashina API認証・実生成、実際の異なるバージョン間brew upgrade、Intel実機、スリープ復帰・翌朝8時の自動実行。追加の実行結果は下に記録します。

## ローカル実機検証

- Apple Silicon / macOS上のHomebrew Python 3.14でpytest **73件成功**。ruff成功。
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
