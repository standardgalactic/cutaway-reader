#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Cutaway Reader — GitHub Pages deployment
#
# Run from the project root:
#
#   ./deploy-pages.sh
#
# Optional:
#
#   ./deploy-pages.sh standardgalactic/cutaway-reader
#
# Publishes GitHub Pages from:
#
#   main / docs
# ------------------------------------------------------------

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

REPO="${1:-standardgalactic/cutaway-reader}"
BRANCH="main"
SITE_DIR="site"
PAGES_DIR="docs"

echo "==> Cutaway GitHub Pages deploy"
echo "    project: $ROOT"
echo "    repo:    $REPO"
echo "    source:  $SITE_DIR/"
echo "    pages:   $PAGES_DIR/"

# ------------------------------------------------------------
# 1. Check required commands
# ------------------------------------------------------------

command -v git >/dev/null 2>&1 || {
    echo "ERROR: git is not installed." >&2
    exit 1
}

command -v gh >/dev/null 2>&1 || {
    echo "ERROR: GitHub CLI (gh) is not installed." >&2
    echo "Install it, then run: gh auth login" >&2
    exit 1
}

if ! gh auth status >/dev/null 2>&1; then
    echo "ERROR: GitHub CLI is not authenticated." >&2
    echo "Run: gh auth login" >&2
    exit 1
fi

# ------------------------------------------------------------
# 2. Validate generated site
# ------------------------------------------------------------

if [[ ! -f "$SITE_DIR/cutaway-reader.html" ]]; then
    echo "ERROR: $SITE_DIR/cutaway-reader.html does not exist." >&2
    exit 1
fi

if [[ ! -d "$SITE_DIR/works" ]]; then
    echo "ERROR: $SITE_DIR/works does not exist." >&2
    exit 1
fi

WORK_COUNT="$(
    find "$SITE_DIR/works" \
        -maxdepth 1 \
        -type f \
        -name '*.json' |
    wc -l
)"

if [[ "$WORK_COUNT" -eq 0 ]]; then
    echo "ERROR: no work JSON files found in $SITE_DIR/works." >&2
    exit 1
fi

echo "==> Found $WORK_COUNT deployable works"

# ------------------------------------------------------------
# 3. Initialize Git if necessary
# ------------------------------------------------------------

if [[ ! -d .git ]]; then
    echo "==> Initializing Git repository"
    git init -b "$BRANCH"
else
    echo "==> Existing Git repository found"

    CURRENT_BRANCH="$(git branch --show-current)"

    if [[ -n "$CURRENT_BRANCH" && "$CURRENT_BRANCH" != "$BRANCH" ]]; then
        echo "==> Switching deployment branch to $BRANCH"

        if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
            git switch "$BRANCH"
        else
            git switch -c "$BRANCH"
        fi
    fi
fi

# ------------------------------------------------------------
# 4. Preserve documentation currently living in docs/
# ------------------------------------------------------------

TMP_DOCS="$(mktemp -d)"

cleanup() {
    rm -rf "$TMP_DOCS"
}

trap cleanup EXIT

if [[ -f "$PAGES_DIR/FORMATS.md" ]]; then
    cp "$PAGES_DIR/FORMATS.md" "$TMP_DOCS/FORMATS.md"
fi

if [[ -f "$PAGES_DIR/SPEC.md" ]]; then
    cp "$PAGES_DIR/SPEC.md" "$TMP_DOCS/SPEC.md"
fi

# ------------------------------------------------------------
# 5. Build docs/ publication tree
# ------------------------------------------------------------

echo "==> Building GitHub Pages tree"

rm -rf "$PAGES_DIR"
mkdir -p "$PAGES_DIR"

# Main reader becomes the website root.
cp "$SITE_DIR/cutaway-reader.html" "$PAGES_DIR/index.html"

# Progressive-loading work files.
cp -R "$SITE_DIR/works" "$PAGES_DIR/works"

# Publish root-level PDFs at the root of the Pages site.
shopt -s nullglob
PDFS=( ./*.pdf )

if ((${#PDFS[@]})); then
    cp "${PDFS[@]}" "$PAGES_DIR/"
    echo "==> Published ${#PDFS[@]} root PDFs"
fi

shopt -u nullglob

# Restore project documentation.
if [[ -f "$TMP_DOCS/FORMATS.md" ]]; then
    cp "$TMP_DOCS/FORMATS.md" "$PAGES_DIR/FORMATS.md"
fi

if [[ -f "$TMP_DOCS/SPEC.md" ]]; then
    cp "$TMP_DOCS/SPEC.md" "$PAGES_DIR/SPEC.md"
fi

# Disable Jekyll processing.
touch "$PAGES_DIR/.nojekyll"

echo "==> Publication tree"

find "$PAGES_DIR" -maxdepth 2 -type f | sort

# ------------------------------------------------------------
# 6. Sanity checks
# ------------------------------------------------------------

if [[ ! -f "$PAGES_DIR/index.html" ]]; then
    echo "ERROR: docs/index.html was not created." >&2
    exit 1
fi

DEPLOYED_WORK_COUNT="$(
    find "$PAGES_DIR/works" \
        -maxdepth 1 \
        -type f \
        -name '*.json' |
    wc -l
)"

if [[ "$DEPLOYED_WORK_COUNT" -ne "$WORK_COUNT" ]]; then
    echo "ERROR: work count changed during deployment." >&2
    echo "Source:   $WORK_COUNT" >&2
    echo "Deployed: $DEPLOYED_WORK_COUNT" >&2
    exit 1
fi

echo "==> Verified $DEPLOYED_WORK_COUNT work files"

# ------------------------------------------------------------
# 7. Connect/create GitHub repository
# ------------------------------------------------------------

if gh repo view "$REPO" >/dev/null 2>&1; then

    echo "==> GitHub repository already exists: $REPO"

    EXPECTED_REMOTE="https://github.com/${REPO}.git"

    if git remote get-url origin >/dev/null 2>&1; then
        CURRENT_REMOTE="$(git remote get-url origin)"

        if [[ "$CURRENT_REMOTE" != "$EXPECTED_REMOTE" &&
              "$CURRENT_REMOTE" != "git@github.com:${REPO}.git" ]]; then

            echo "ERROR: origin points somewhere unexpected:"
            echo "       $CURRENT_REMOTE"
            echo
            echo "Expected repository:"
            echo "       $REPO"
            exit 1
        fi
    else
        git remote add origin "$EXPECTED_REMOTE"
    fi

else

    echo "==> Creating GitHub repository: $REPO"

    gh repo create "$REPO" \
        --public \
        --source=. \
        --remote=origin
fi

# ------------------------------------------------------------
# 8. Commit
# ------------------------------------------------------------

echo "==> Staging repository"

git add -A

if git diff --cached --quiet; then
    echo "==> Nothing new to commit"
else
    git commit -m "Deploy Cutaway Reader"
fi

# ------------------------------------------------------------
# 9. Push
# ------------------------------------------------------------

echo "==> Pushing $BRANCH"

git push -u origin "$BRANCH"

# ------------------------------------------------------------
# 10. Configure GitHub Pages: main / docs
# ------------------------------------------------------------

echo "==> Configuring GitHub Pages from $BRANCH:/docs"

if gh api "repos/$REPO/pages" >/dev/null 2>&1; then

    # Pages already exists. Ensure it points at main:/docs.
    gh api \
        --method PUT \
        "repos/$REPO/pages" \
        -f "source[branch]=$BRANCH" \
        -f 'source[path]=/docs' \
        >/dev/null

else

    # First Pages deployment.
    gh api \
        --method POST \
        "repos/$REPO/pages" \
        -f "source[branch]=$BRANCH" \
        -f 'source[path]=/docs' \
        >/dev/null
fi

# ------------------------------------------------------------
# 11. Report result
# ------------------------------------------------------------

OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

echo
echo "=============================================="
echo " Cutaway Reader deployed"
echo "=============================================="
echo
echo "Repository:"
echo "  https://github.com/$REPO"
echo
echo "GitHub Pages:"
echo "  https://${OWNER}.github.io/${NAME}/"
echo
echo "Publishing source:"
echo "  $BRANCH:/docs"
echo
