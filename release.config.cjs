/**
 * Unified release for the newswitch monorepo.
 * One version, one tag (vX.Y.Z), both packages bumped and shipped together.
 * GitHub Releases only - nothing is published to PyPI or npm.
 */
module.exports = {
  branches: ["main"],
  tagFormat: "v${version}",
  plugins: [
    ["@semantic-release/commit-analyzer", { preset: "conventionalcommits" }],
    ["@semantic-release/release-notes-generator", { preset: "conventionalcommits" }],
    ["@semantic-release/changelog", { changelogFile: "CHANGELOG.md" }],
    [
      "@semantic-release/exec",
      {
        // The frontend build generates src/apps/default/** from the committed schema
        // export (frontend/schemas/); no backend runs in CI.
        prepareCmd: [
          "(cd backend && uv version --no-sync '${nextRelease.version}')",
          "(cd frontend && npm version '${nextRelease.version}' --no-git-tag-version --allow-same-version)",
          "(cd frontend && yarn build)",
          "rm -f blok.zip && (cd frontend/dist && zip -qr ../../blok.zip .)",
          "(cd backend && uv build --out-dir dist)",
        ].join(" && "),
      },
    ],
    [
      "@semantic-release/git",
      {
        assets: [
          "CHANGELOG.md",
          "backend/pyproject.toml",
          // uv.lock embeds the project's own version
          "backend/uv.lock",
          "frontend/package.json",
        ],
        message: "chore(release): v${nextRelease.version} [skip ci]\n\n${nextRelease.notes}",
      },
    ],
    [
      "@semantic-release/github",
      {
        assets: [
          { path: "blok.zip", label: "Frontend bundle (blok.zip)" },
          { path: "backend/dist/*.whl", label: "Backend wheel" },
          { path: "backend/dist/*.tar.gz", label: "Backend sdist" },
        ],
      },
    ],
  ],
};
