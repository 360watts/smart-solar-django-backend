#!/bin/bash
# Pre-commit hook to prevent committing secrets/credentials
# Place this file in .git/hooks/pre-commit and make it executable
# chmod +x .git/hooks/pre-commit

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${YELLOW}[Pre-commit Hook] Checking for secrets...${NC}"

# Files and patterns that should never be committed
FORBIDDEN_FILES=(
    "\.env"
    "\.env\."
    "\.env\.local"
    "\.env\.pg"
    "\.env\.secret"
    "\.env\.prod"
    "secrets\.txt"
    "credentials\.json"
    "private_key"
)

FORBIDDEN_PATTERNS=(
    "postgres://.*:.*@"           # PostgreSQL URIs
    "mongodb://.*:.*@"            # MongoDB URIs
    "mysql://.*:.*@"              # MySQL URIs
    "password[\"']?\s*[:=]"       # password assignments
    "secret[\"']?\s*[:=]"         # secret assignments
    "api[_-]?key[\"']?\s*[:=]"    # API key assignments
    "bearer[_-]?token[\"']?\s*[:=]" # Bearer tokens
    "authorizatio\n[\"']?\s*[:=]" # Authorization headers
)

# Get list of staged files
STAGED_FILES=$(git diff --cached --name-only)

# Check staged files for forbidden filenames
echo "Checking file names..."
for file in $STAGED_FILES; do
    for forbidden in "${FORBIDDEN_FILES[@]}"; do
        if [[ "$file" =~ $forbidden ]]; then
            echo -e "${RED}✗ ERROR: Cannot commit file matching pattern '$forbidden'${NC}"
            echo "  File: $file"
            echo ""
            echo "Prevention tip:"
            echo "  - Don't commit .env files"
            echo "  - Add them to .gitignore"
            echo "  - Use .env.example instead"
            echo ""
            echo "To bypass this check (NOT RECOMMENDED):"
            echo "  git commit --no-verify"
            exit 1
        fi
    done
done

# Check staged content for forbidden patterns
echo "Checking file content..."
LEAKED_SECRETS=0

for file in $STAGED_FILES; do
    # Skip binary files and non-text files
    if file "$file" | grep -q "binary"; then
        continue
    fi

    # Get the staged content
    CONTENT=$(git show :"$file" 2>/dev/null || cat "$file")

    for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
        if echo "$CONTENT" | grep -i "$pattern" > /dev/null; then
            echo -e "${RED}✗ WARNING: Possible secret detected in $file${NC}"
            echo "  Pattern: $pattern"
            LEAKED_SECRETS=$((LEAKED_SECRETS + 1))
        fi
    done
done

if [ $LEAKED_SECRETS -gt 0 ]; then
    echo ""
    echo -e "${RED}✗ Found $LEAKED_SECRETS potential secrets in staged changes${NC}"
    echo ""
    echo "What to do:"
    echo "  1. Remove the secret from the file"
    echo "  2. Stage the corrected file: git add <file>"
    echo "  3. Commit again"
    echo ""
    echo "If these are false positives:"
    echo "  git commit --no-verify"
    echo ""
    echo "If you're panicking:"
    echo "  - Reset staged changes: git reset HEAD"
    echo "  - Verify before re-staging: git diff"
    exit 1
fi

echo -e "${GREEN}✓ Pre-commit check passed - no secrets detected${NC}"
exit 0
