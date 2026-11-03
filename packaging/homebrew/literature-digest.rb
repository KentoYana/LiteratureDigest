class LiteratureDigest < Formula
  include Language::Python::Virtualenv

  desc "Turn science RSS feeds into concise Japanese news with Sarashina"
  homepage "https://github.com/KentoYana/LiteratureDigest"
  url "https://github.com/KentoYana/LiteratureDigest/releases/download/v1.0.0/literature_digest-1.0.0.tar.gz"
  sha256 "45dde31fae3f4981e2f1b8a2b06e0fbb9f9d06533119fb28089a1a42bca275fc"
  license "MIT"

  depends_on "libyaml"
  depends_on :macos
  depends_on "python@3.14"

  resource "defusedxml" do
    url "https://files.pythonhosted.org/packages/0f/d5/c66da9b79e5bdb124974bfe172b4daf3c984ebd9c2a06e2b8a4dc7331c72/defusedxml-0.7.1.tar.gz"
    sha256 "1bb3032db185915b62d7c6209c5a8792be6a32ab2fedacc84e01b52c51aa3e69"
  end

  resource "feedparser" do
    url "https://files.pythonhosted.org/packages/37/8a/a53da4a77352045d277978a2df322d5379369f9deb1707178899ff7e1121/feedparser-6.0.14.tar.gz"
    sha256 "088679b0c4b543ee211a820dd544698c76a402122eae7473c04a43425f283d06"
  end

  resource "feedparser-sgmllib" do
    url "https://files.pythonhosted.org/packages/da/df/38596299216e5c22d60ed7f97902bb2bc72cfb95f732400f4fa976fd2e62/feedparser_sgmllib-2.1.0.tar.gz"
    sha256 "61facf2918c4389b5b00714f76c5e03431ffcd94cd1f51d657edd6cd7c396579"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  def install
    virtualenv_install_with_resources(system_site_packages: false)
    pkgshare.install "scripts/package_smoke.py"
  end

  def caveats
    <<~EOS
      Initialize user-owned configuration (existing files are kept):
        literature-digest init
      Configure feeds and an API key using the README:
        https://github.com/KentoYana/LiteratureDigest#初期設定とapiキー
      Start local processing and serving explicitly:
        literature-digest run
        literature-digest service install
        literature-digest service start
      NetNewsWire feed: http://127.0.0.1:8080/feed.xml
      Upgrade and uninstall retain configuration, articles, logs and Keychain items.
      Before uninstalling, remove LaunchAgents with:
        literature-digest service uninstall
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/literature-digest --version")
    system libexec/"bin/python", pkgshare/"package_smoke.py",
           "--command", bin/"literature-digest", "--workdir", testpath/"smoke"
  end
end
