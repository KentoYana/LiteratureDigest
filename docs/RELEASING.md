# リリースとTap公開

## 状態の区別

- 公開準備済み：ソース、テスト、実在依存アーカイブのresourceロック、Formulaテンプレート、CIが存在する状態。
- 公開済み：`KentoYana/LiteratureDigest`の固定タグとRelease assetが存在し、assetの実測SHA-256を使用するFormulaが`KentoYana/homebrew-tap`へ反映された状態。
- v1.0完成：上記に加えHomebrewの新規インストール・testと仕様の必要な実機試験が終了した状態。未検証事項はVALIDATION.mdへ残す。

本番キーがない場合はSarashinaへの実リクエストを成功と報告しません。

## 最初の公開

標準の`gh auth login`またはGitHub Actionsの`GITHUB_TOKEN`を使用します。秘密をファイルに保存しません。アプリとTapの作成・push権限が必要です。Tapが既存の場合は他Formulaや作業中の変更を維持してください。

```sh
gh repo view KentoYana/LiteratureDigest
# 未作成の場合だけ：
# gh repo create KentoYana/LiteratureDigest --public --source . --remote origin
```

`pyproject.toml`と`src/literature_digest/__init__.py`を同じSemVerへ更新します。新バージョン時はCIのアーカイブ名とpackage_smoke.pyの期待版も更新してください。

```sh
python -m pip install -e '.[dev]'
ruff check src tests scripts
pytest -q
python -m build
```

公開前に、実在するローカルアーカイブからFormulaを生成して試験できます。file URLは公開Tapへコミットしないでください。

```sh
brew tap-new local/literature-digest-test
python scripts/render_formula.py \
  --archive dist/literature_digest-1.0.0.tar.gz \
  --output "$(brew --repository local/literature-digest-test)/Formula/literature-digest.rb"
brew install --build-from-source local/literature-digest-test/literature-digest
brew test local/literature-digest-test/literature-digest
brew audit local/literature-digest-test/literature-digest
literature-digest --version
literature-digest --home /tmp/ld-package-test init
literature-digest --home /tmp/ld-package-test doctor --offline
brew uninstall literature-digest
```

タグをpushするとrelease.ymlがテスト・ビルド・Release公開・Formula生成を行います。

```sh
git add .
git commit -m "Release LiteratureDigest 1.0.0"
git push -u origin main
git tag -a v1.0.0 -m 'LiteratureDigest 1.0.0'
git push origin v1.0.0
```

`TAP_GITHUB_TOKEN`にTapリポジトリだけのContents read/write権限を持つfine-grained tokenを登録した場合、Tap更新とHomebrew試験も自動化します。標準`GITHUB_TOKEN`は別リポジトリへpushできないため、このSecretがなければFormula artifactを生成して手動引き継ぎします。

## 手動公開・復旧

自動公開と同じタグに重複Releaseを作成しないでください。失敗した場合は原因を修正して実在するassetとタグを確認します。公開済みタグは書き換えず、アプリコードの修正は次のパッチ版を作成します。

```sh
shasum -a 256 dist/literature_digest-1.0.0.tar.gz
# Releaseがまだ存在しない場合だけ：
gh release create v1.0.0 dist/literature_digest-1.0.0.tar.gz dist/*.whl \
  --verify-tag --title 'LiteratureDigest v1.0.0' --generate-notes
python scripts/render_formula.py \
  --archive dist/literature_digest-1.0.0.tar.gz \
  --url https://github.com/KentoYana/LiteratureDigest/releases/download/v1.0.0/literature_digest-1.0.0.tar.gz \
  --output packaging/homebrew/literature-digest.rb
```

render_formula.pyは公開アーカイブを実際にダウンロードし、手元のアーカイブとSHA-256が一致した場合だけFormulaを出力します。Release CIが作ったアーカイブを使う場合は、先に`gh release download v1.0.0 --pattern '*.tar.gz' --dir /tmp/ld-release`で取得し、そのファイルを`--archive`に渡してください。

Tapリポジトリへ同一Formulaをコピーします。

```sh
git clone https://github.com/KentoYana/homebrew-tap.git /tmp/ld-tap
cp packaging/homebrew/literature-digest.rb /tmp/ld-tap/Formula/literature-digest.rb
git -C /tmp/ld-tap add Formula/literature-digest.rb
git -C /tmp/ld-tap commit -m 'literature-digest 1.0.0'
git -C /tmp/ld-tap push
brew tap KentoYana/tap
brew update
brew audit KentoYana/tap/literature-digest
brew install --build-from-source KentoYana/tap/literature-digest
brew test KentoYana/tap/literature-digest
literature-digest --version
literature-digest --home /tmp/ld-release-test init
literature-digest --home /tmp/ld-release-test doctor --offline
```

## 依存関係の更新

```sh
brew update-python-resources --print-only KentoYana/tap/literature-digest
```

出力を検討し、`pyproject.toml`と`packaging/homebrew/resources.json`を同時更新します。推移的依存も含め、実在するsdistのURLと実測またはPyPI公表SHA-256を記録します。FormulaのPythonを変更する場合はHomebrewの現行指針、依存の対応状況を確認します。現在はローカル検証可能なPython 3.14を明示使用し、ホストPythonのsite-packagesを継承しません。

## 更新・削除でのデータ保持

CIでは独自ユーザーディレクトリに設定・DB・RSSを作り、`brew reinstall`と`brew uninstall`前後にSHA-256を比較します。reinstallは同版での保持試験であり、実際の異なるリリース間`brew upgrade`試験とは区別して記録してください。将来のDB変更は`database.MIGRATIONS`に追加し、旧版DBを用いるテストを追加します。
