#!/bin/bash

# BerlinFlatBot Git Workflow Script
# This script automates: develop_secret -> develop -> commit -> merge back to develop_secret

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if commit message is provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Commit message required${NC}"
    echo "Usage: ./commit-and-merge.sh \"Your commit message\""
    exit 1
fi

COMMIT_MESSAGE="$1"

echo -e "${YELLOW}🔄 Starting automated git workflow...${NC}\n"

# Check current branch
CURRENT_BRANCH=$(git branch --show-current)
echo -e "Current branch: ${GREEN}$CURRENT_BRANCH${NC}"

if [ "$CURRENT_BRANCH" != "develop_secret" ]; then
    echo -e "${RED}Error: Must be on develop_secret branch${NC}"
    exit 1
fi

# Check for uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo -e "${GREEN}✓ Found uncommitted changes${NC}"
else
    echo -e "${RED}Error: No changes to commit${NC}"
    exit 1
fi

# Stash changes
echo -e "\n${YELLOW}📦 Stashing changes...${NC}"
git stash

# Switch to develop
echo -e "\n${YELLOW}🔀 Switching to develop branch...${NC}"
git checkout develop

# Pop stashed changes
echo -e "\n${YELLOW}📤 Applying changes to develop...${NC}"
git stash pop

# Add all changes
echo -e "\n${YELLOW}➕ Staging changes...${NC}"
git add -A

# Show what will be committed
echo -e "\n${YELLOW}📝 Changes to be committed:${NC}"
git status --short

# Commit with the provided message (adding Claude signature)
echo -e "\n${YELLOW}💾 Committing to develop...${NC}"
git commit -m "${COMMIT_MESSAGE}

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Get the commit hash
COMMIT_HASH=$(git rev-parse --short HEAD)
echo -e "${GREEN}✓ Committed: $COMMIT_HASH${NC}"

# Switch back to develop_secret
echo -e "\n${YELLOW}🔙 Switching back to develop_secret...${NC}"
git checkout develop_secret

# Merge develop into develop_secret
echo -e "\n${YELLOW}🔗 Merging develop into develop_secret...${NC}"
git merge develop --no-edit

# Show final status
echo -e "\n${GREEN}✅ Workflow complete!${NC}\n"
echo -e "Summary:"
echo -e "  - Committed to ${GREEN}develop${NC}: $COMMIT_HASH"
echo -e "  - Merged to ${GREEN}develop_secret${NC}"
echo -e "  - Currently on: ${GREEN}$(git branch --show-current)${NC}"
echo -e "\nRecent commits:"
git log --oneline -3

echo -e "\n${YELLOW}Note: Config secrets remain safe in develop_secret only${NC}"
