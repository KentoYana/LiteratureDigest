# LiteratureDigest v1.0.0

RSS/Atomから科学論文を収集し、Sarashinaで短い日本語記事へ編集して、localhost上のRSS 2.0として配信するCLIの初回リリースです。

- DOI/PMIDを優先した重複排除、後日のDOI補完、SQLite永続化と異常終了からの回収。
- Sarashina JSON Schema出力、文字数・型・HTML検証、タイムアウト/429/5xxの上限付き再試行。
- PubMedによる抄録補完。抄録がない論文は書誌情報のみ配信。
- localhost限定HTTP、バッチとHTTPを分離したLaunchAgent、キーチェーン認証。
- Homebrew独自Tap、専用Python環境、ユーザー設定・記事を保持する更新と削除。

```sh
brew install KentoYana/tap/literature-digest
literature-digest init
```

初期フィード一覧は空です。READMEに従い購読先とAPIキーを設定し、手動実行後にサービスを明示的に開始してください。brew installだけでは自動起動しません。

ローカルでpytest 73件、brew install/audit/test、実機LaunchAgent起動、localhost待受、パッケージrevisionのbrew upgradeとアンインストール後のデータ保持を確認しました。macOS/Linux × Python 3.11/3.14のCIとmacOSパッケージングCIを用意しています。

本番Sarashina APIキーによる実生成、NetNewsWireでの購読と本文の目視確認、翌朝の定刻実行・スリープ復帰、Intel実機、異なるアプリ版間のアップグレードは未検証です。全完成条件の実機確認が済んだとは扱いません。

[導入・運用方法](https://github.com/KentoYana/LiteratureDigest#readme)・[検証記録](https://github.com/KentoYana/LiteratureDigest/blob/main/docs/VALIDATION.md)
