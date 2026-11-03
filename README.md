# LiteratureDigest

複数のRSS/Atomフィードから科学論文の新着を収集し、Sarashina APIで200〜350字の日本語記事に編集するmacOS用CLIです。SQLiteで新着・重複・書誌情報を管理し、RSS 2.0をNetNewsWireへローカル配信します。LLMは記事の編集だけに使用します。

## Homebrewでインストール

```sh
brew install KentoYana/tap/literature-digest
literature-digest --version
literature-digest init
```

PythonはFormulaが専用仮想環境へ導入します。利用者のpyenv・pip操作は不要です。Apple SiliconとIntelのHomebrew prefixを自動判定します。インストールだけでは収集もHTTP配信も開始しません。

公開・試験の実施状況は [検証記録](docs/VALIDATION.md) を参照してください。ReleaseとTapが公開される前は、上のコマンドは利用できません。[公開手順](docs/RELEASING.md)で「準備済み」と「公開済み」を区別します。

## 初期設定とAPIキー

`init`は既存の設定を上書きしません。保存先は次のとおりです。

```text
~/Library/Application Support/LiteratureDigest/
  config/feeds.yaml
  config/settings.yaml
  data/literature.db
  public/feed.xml
~/Library/Logs/LiteratureDigest/
```

APIキーを設定ファイル、`.env`、ソース、DBに記入しないでください。手動実行時はzshで、履歴にキーを残さず入力できます。

```sh
read -s 'SARASHINA_API_KEY?Sarashina API key: '; echo
export SARASHINA_API_KEY
literature-digest doctor
```

自動実行にはmacOSのログインキーチェーンを使用します。以下はパスワードを対話入力するため、`-w`を最後に置いてください（キーを引数に書かない）。

```sh
security add-generic-password -U -a "$USER" -s ai.sarashina.LiteratureDigest -w
```

キーを入力してから `unset SARASHINA_API_KEY` を実行し、`literature-digest doctor`でキーチェーン経由の認証情報検出を確認してください。キーの値は表示しません。環境変数がある場合はそちらを優先します。初回はmacOSのアクセス許可が必要になる場合があります。ログインキーチェーンがロック中の無人実行は認証に失敗するため、ログイン後に一度手動実行を確認してください。doctorは課金APIを呼ばず、キーの有無を診断します。認証情報の有効性は実際のgenerate/runで確認します。

## RSS購読先の登録

```sh
open -e "$HOME/Library/Application Support/LiteratureDigest/config/feeds.yaml"
```

初期設定は空です。出版社・データベースの公式RSS URLを確認し、次の形式で登録します。

```yaml
feeds:
  - id: my-journal
    name: My Journal
    url: https://example.org/feed.xml  # 実在する購読先URLに置換
    enabled: true
    category: biology
```

RSS 2.0とAtomに対応します。フィード名を雑誌名と推測することはありません。取得できない著者・雑誌・公開日・識別子は空値で保持します。抄録がない場合はPMIDまたはDOIでPubMed E-utilitiesから補完し、DOI一致も確認します。NCBIへのアクセスは3回/秒以下に制限します。`settings.yaml`の`metadata.email`に連絡先を設定することを推奨します。出版社のページやPDFは取得しません。

PubMedにも抄録がない場合は`skipped`として書誌情報だけを配信します。抄録なしの再照会を毎日繰り返すことはありません。後からフィードに抄録が追加されれば自動回収します。API一時障害は`failed`で保持し、次回に再試行します。

## 手動実行

```sh
literature-digest run
literature-digest status
literature-digest serve
```

別のターミナルで次を確認します。

```sh
curl -f http://127.0.0.1:8080/feed.xml
literature-digest doctor
```

`collect`、`generate`、`publish`も個別に実行できます。`generate`/`run`は標準で最大20件を編集し、残りは次回へ回します。新着も未処理もなければLLMを呼び出しません。`--limit N`は収集時には各フィードの取得上限、生成時には実行全体の上限です。`--dry-run`は予定のみを表示し、ネットワーク・キーの読み出し・ファイル更新・サービス操作を行いません。`--verbose`はログの詳細度を変更します。

```sh
literature-digest run --limit 5
literature-digest run --dry-run
literature-digest --home /tmp/literature-digest-dev init
LITERATURE_DIGEST_HOME=/tmp/literature-digest-dev literature-digest status
```

DOI→PMID→フィード固有ID→正規化URL→完全一致の補助書誌情報の順で照合します。異なるDOI/PMIDを持つ記事をタイトルの類似性で統合しません。元のタイトル・URL・DOI表記はDBの書誌情報と取得エントリに保持し、識別用DOIだけを正規化します。GUIDは初回登録時に永続化し、再配信で変更しません。

原文中の命令は信頼できない入力として扱います。出力はJSON構造、日本語文字、見出し1〜60字、本文200〜350字、HTML・制御文字、正常終了理由を検証します。文字数違反のみ1回再生成します。自動検証は科学的正確性を保証しません。記事にはAI生成の表示と原著の書誌情報を付けます。

## launchdによる自動実行

先に手動実行とキーチェーンでのキー取得を確認してください。手動の`serve`はCtrl-Cで終了してから自動配信を開始します。

```sh
literature-digest service install
literature-digest service start
literature-digest service status
```

ユーザーの `~/Library/LaunchAgents/` にバッチ用とHTTP用の2つのplistを作成します。`install`はファイル作成、`start`はlaunchdへの登録です。バッチは平日8:00のローカルシステム時刻、HTTPは登録時とログイン時に起動し、異常終了時に再起動します。ログアウト中・スリープ中の常時動作は保証されません。必要に応じてMacの電源・スリープ設定を調整してください。

```sh
literature-digest service stop
literature-digest service start --target http
literature-digest service uninstall
```

`--target batch|http|all`で個別管理できます。`settings.yaml`の`schedule`はlaunchdのWeekday（0=日、1=月、…6=土）、hour、minuteです。変更時は`service uninstall`→`service install`→`service start`で反映します。既存plistは暗黙に上書きしません。登録先バイナリは実際の`brew --prefix`にある`bin/literature-digest`で、Cellarのバージョン番号やpyenvに依存しません。pip版で登録する場合は `service install --binary /absolute/path/to/.venv/bin/literature-digest` を使用します。

バッチはファイルロックで重複起動を防ぎます。異常終了後の`processing`記事は次のgenerate/runで回収します。API呼び出し成功後、DB保存前にプロセスが強制終了した場合は、次回にAPIを再度呼ぶ可能性があります（外部APIを含む厳密なexactly-onceは保証しません）。完成済み記事を通常の再実行で再生成することはありません。

## NetNewsWireで購読

NetNewsWireの「File → New Feed…」から次を登録します。

```text
http://127.0.0.1:8080/feed.xml
```

`content:encoded`に記事全文、`link`に原著URLを格納します。別の端末ではこのURLを購読できません。待受は127.0.0.1のみ、配信対象は`/feed.xml`のみです。ディレクトリ一覧、設定、DBを配信しません。ポート変更時は `settings.yaml`の`server.port`を編集し、HTTPサービスを停止・開始して購読URLも変更してください。配信件数は`publisher.limit`（初期100件）です。

## アップデートとログ

```sh
brew update
brew upgrade KentoYana/tap/literature-digest
literature-digest --version
literature-digest doctor
literature-digest service stop --target http
literature-digest service start --target http
```

HTTPサービスの再起動で新しいコードを読み込みます。設定・DB・記事・キー・plistはCellarの外にあり、upgradeで初期化しません。DBスキーマはバージョン付きマイグレーションで管理し、未知の新しいDBを古いアプリで変更しません。将来の移行前にはサービス停止後にユーザーディレクトリをバックアップしてください。

```sh
tail -n 100 "$HOME/Library/Logs/LiteratureDigest/literature-digest.log"
```

標準loggingを使用し、アプリログは2MB×4ファイルにローテーションします。launchdの標準出力・標準エラーは同ディレクトリのbatch/httpログです。APIキー、抄録全文、API応答全文はログに記録しません。

## トラブルシューティング

- `doctor`：設定、Python、同梱テンプレート、DB整合性、認証情報の有無、HTTPを確認。APIへの有料リクエストは送信しません。`doctor --offline`は認証とHTTP確認を省略します。
- `missing_api_key`/`http_401`/`http_403`：キーとキーチェーンのアクセス許可を確認。その実行のバッチ処理を打ち切り、残りの記事への認証リトライをしません。
- `http_429`：Retry-Afterを守り、上限付きで再試行。300秒を超える待機は次回実行へ延期します。
- ネットワーク・タイムアウト・5xx：上限付き指数バックオフで再試行。失敗はDBに保持して次回回収します。
- `invalid_length`/`invalid_json`/`incomplete_output`：成功扱いにせずfailedとして保持。文字数だけ1回再生成します。必要に応じて生成トークン上限を調整してください。
- 記事なし：feeds.yamlのenabled、URL、`status`のfeed_errors、抄録の有無を確認。初期フィード一覧は空です。
- ポート使用中：手動serveとサービスの二重起動を避けるかポートを変更。
- 「別の処理が実行中」：既存処理が終了するまで待つ。lockファイルは削除せず、OSのロック解放に任せます。

プロンプトを変更する場合は次でユーザー領域へコピーし、`config/digest.md`を編集します。生成時に内容のSHA-256をDBへ保存します。

```sh
literature-digest init --copy-prompt
open -e "$HOME/Library/Application Support/LiteratureDigest/config/digest.md"
```

## アンインストール

```sh
literature-digest service uninstall
brew uninstall KentoYana/tap/literature-digest
```

ユーザー設定・DB・記事・ログ・キーチェーンは残ります。再インストールで引き継げます。以下は完全削除を希望する場合だけ実行してください。

```sh
rm -rf "$HOME/Library/Application Support/LiteratureDigest"
rm -rf "$HOME/Library/Logs/LiteratureDigest"
security delete-generic-password -a "$USER" -s ai.sarashina.LiteratureDigest
```

独自`--home`のデータはその場所から手動で削除します。Formulaにはpost_installやサービス自動登録、データ削除フックを置きません。

## 開発環境（pyenv・pip）

Python 3.11以上。macOS用のサービス・キーチェーン機能以外はLinux上のCIでも検証します。Dockerは使用しません。

```sh
git clone https://github.com/KentoYana/LiteratureDigest.git
cd LiteratureDigest
pyenv install -s 3.14.0
pyenv local 3.14.0
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest -q
ruff check src tests scripts
python -m build
literature-digest --home /tmp/literature-digest-dev init
literature-digest --home /tmp/literature-digest-dev doctor --offline
```

開発版CLIも同じ`project.scripts`を使用し、テンプレートは`importlib.resources`でパッケージから読みます。カレントディレクトリには依存しません。テストは外部APIや本番キーを不要とし、RSS/Atom、識別子競合、永続化、再実行、HTTPリトライ、出力検証、RSS、安全なHTTP配信、秘密情報非出力を検証します。

## FormulaとReleaseの管理

詳細は [公開手順](docs/RELEASING.md)。管理用原本は`packaging/homebrew/literature-digest.rb.in`です。実在するアーカイブからURLとSHA-256を取得して`.rb`を生成し、Tapの`Formula/literature-digest.rb`へ同一内容を反映します。存在しないURL・推測チェックサムは記録しません。

`Language::Python::Virtualenv`と`virtualenv_install_with_resources`を使用し、実行時依存は推移的依存を含めて全てresource化しています。`brew update-python-resources --print-only KentoYana/tap/literature-digest`で更新候補を確認し、生成スクリプト側のロックも同時に更新してください。

公式資料：[Homebrew Python指針](https://docs.brew.sh/Language-Specific-Formulae)、[Sarashina Chat Completions](https://docs.sarashina.ai/api-reference/chat-completions)、[レート制限](https://docs.sarashina.ai/rate-limits)、[NCBI E-utilities利用条件](https://www.ncbi.nlm.nih.gov/books/NBK25497/)（2026-11-03確認）。

GUI、RAG、PDF解析、メール、推薦、複数論文の統合、インターネット公開はv1.0の対象外です。
