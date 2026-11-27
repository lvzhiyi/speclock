#!/usr/bin/env python3
"""SpecLock (workflow-core) documentation validator (read-only, Python stdlib only).

Checks:
1. Local relative links and heading anchors across agent entry files, engineering docs, and product docs.
2. Task cards: required fields, completion checkbox vs. non-terminal status consistency, and structured Pending items.
3. Glossary (when docs.glossary is configured): unique term headings and required Definition / 定义 field.

Paths are read from ai-workflow.yaml at project root (see workflow_config.py), with CLI overrides and defaults.
Usage: python3 check_docs.py [--root ROOT] [--product-root DIR] [--cards-dir DIR] [--dev-docs DIR] [--check-config]
Exit codes: 0 passed; 1 check failed; 2 blocked (missing root or invalid configuration).
"""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote

from workflow_config import ConfigError, is_placeholder, load as load_config

# Task card heading pattern: ### <MODULE>-R<N> <Title>
DEFAULT_CARD_ID = r'[A-Z][A-Z0-9]*-R\d+'

# Required task card fields (bilingual English / Chinese).
CARD_REQUIRED = {
    'completion checkbox': re.compile(r'^- \[[ xX]\] ', re.M),
    'Source / 来源': re.compile(r'^- (?:来源|Source)[：:]', re.M | re.I),
    'Acceptance / 验收': re.compile(r'^- (?:验收|Acceptance)[：:]', re.M | re.I),
}

# Completion checkbox and status extraction (supports both standalone Status and "Status / Priority" prefixes).
CARD_CHECKED = re.compile(r'^- \[[xX]\] ', re.M)
CARD_STATUS = re.compile(
    r'^- (?:(?:协作状态|状态|Status)(?:[ \t]*/[^：:\n]+)?[：:]|\*\*(?:协作状态|状态|Status)\*\*[：:]|\*\*(?:协作状态|状态|Status)[：:]\*\*)[ \t]*(.*?)'
    r'[ \t]*(?:[；;/].*|<!--.*)?$',
    re.M | re.I,
)

# Non-terminal status keywords that must not coexist with a checked [x] box.
NON_TERMINAL_STATUS_KEYWORDS = (
    '待处理', '待确认', '待验证', '待评审', '待人工验收', '待开发', '待实施',
    '未开始', '研发中', '实施中', '进行中', '评审未通过', '受阻', '阻塞', '已暂停', '已取消',
    'pending', 'not started', 'in progress', 'implementing', 'blocked',
    'review failed', 'pending human acceptance', 'pending verification', 'cancelled',
)

# Structured Pending / 待确认 line parsing (when containing '|' or '｜').
PENDING_HEAD = re.compile(r'^(?:待确认|Pending(?:\s+Clarification)?)(?:\s*[（(]([^）)]+)[）)])?\s*[:：]\s*(.*)$', re.I)
PENDING_FIELD_KEYS = {
    '影响': 'impact',
    'impact': 'impact',
    '恢复条件': 'resume',
    'resume': 'resume',
    'resume when': 'resume',
    'resume condition': 'resume',
}


def check_pending_line(line):
    """Validate a structured bilingual Pending item; return missing field labels."""
    if not line.startswith('- ') or ('｜' not in line and '|' not in line):
        return []
    parts = re.split(r'[｜|]', line[2:])
    head = PENDING_HEAD.match(parts[0].strip())
    if not head:
        return []
    is_chinese = parts[0].strip().startswith('待确认')
    fields = {'question': head.group(2).strip()}
    for part in parts[1:]:
        pair = re.split(r'[:：]', part.strip(), maxsplit=1)
        if len(pair) == 2:
            key = PENDING_FIELD_KEYS.get(pair[0].strip().lower())
            if key and pair[1].strip():
                fields[key] = pair[1].strip()
    labels = (
        (('question', '待确认：'), ('impact', '影响：'), ('resume', '恢复条件：'))
        if is_chinese
        else (('question', 'Pending:'), ('impact', 'Impact:'), ('resume', 'Resume when:'))
    )
    return [label for key, label in labels if not fields.get(key)]


def resolve_paths(root, args, config):
    """Resolve (product_root, cards_dir, dev_docs) from CLI args, config, and bilingual defaults."""
    product = args.product_root or config.get('docs.product_root') or 'docs/product'
    cards = args.cards_dir or config.get('docs.cards_dir')
    if not cards:
        if (root / product / 'tasks').is_dir():
            cards = f'{product}/tasks'
        elif (root / product / '任务').is_dir():
            cards = f'{product}/任务'
        else:
            cards = f'{product}/tasks'
    dev = args.dev_docs or config.get('docs.dev_docs') or 'docs/development'
    return root / product, root / cards, root / dev


def check_glossary(root, path):
    """Validate glossary entries: each ### heading must be unique and include '- Definition:' or '- 定义：'."""
    errors = []
    content = path.read_text(encoding='utf-8')
    rel = path.relative_to(root)
    entries = list(re.finditer(r'^###\s+(.+?)\s*$', content, re.M))
    seen = set()
    for index, match in enumerate(entries):
        term = match.group(1)
        end = entries[index + 1].start() if index + 1 < len(entries) else len(content)
        section = re.split(r'^## ', content[match.end():end], maxsplit=1, flags=re.M)[0]
        if term in seen:
            errors.append(f'{rel}: duplicate glossary term "{term}"')
        seen.add(term)
        if not re.search(r'^- (?:Definition|定义)[：:]\s*\S', section, re.M | re.I):
            errors.append(f'{rel}: glossary term "{term}" missing Definition')
    return errors


def heading_slugs(text):
    """Compute GitHub-style Markdown heading anchor slugs, appending -1, -2 for duplicates."""
    seen = {}
    slugs = set()
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f'{slug}-{count}')
    return slugs


def check_links(root, paths):
    """Validate local relative Markdown links and heading anchors (external URI schemes skipped)."""
    errors = []
    cache = {}
    for path in paths:
        content = path.read_text(encoding='utf-8')
        for target in re.findall(r'\[[^\]]*\]\(([^\s)]+)\)', content):
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            name, _, anchor = unquote(target).partition('#')
            dest = (path.parent / name).resolve() if name else path
            rel = path.relative_to(root)
            if not dest.exists():
                errors.append(f'{rel}: broken link target {target}')
            elif anchor and dest.suffix == '.md':
                if dest not in cache:
                    cache[dest] = heading_slugs(dest.read_text(encoding='utf-8'))
                if anchor not in cache[dest]:
                    errors.append(f'{rel}: missing heading anchor {target}')
    return errors


def check_cards(root, cards_dir, card_id=DEFAULT_CARD_ID):
    """Validate task cards: required fields, checkbox vs. status consistency, and structured Pending items."""
    errors = []
    heading = re.compile(rf'^###\s+({card_id})\b.*$', re.M)
    for path in sorted(cards_dir.glob('*.md')):
        content = path.read_text(encoding='utf-8')
        rel = path.relative_to(root)
        matches = list(heading.finditer(content))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            section = re.split(r'^## ', content[match.end():end], maxsplit=1, flags=re.M)[0]
            cid = match.group(1)
            for field, pattern in CARD_REQUIRED.items():
                if not pattern.search(section):
                    errors.append(f'{rel}: {cid} missing required field "{field}"')
            if CARD_CHECKED.search(section):
                status_match = CARD_STATUS.search(section)
                if status_match:
                    status_value = status_match.group(1).strip()
                    lowered_status = status_value.lower()
                    if any(keyword in lowered_status for keyword in NON_TERMINAL_STATUS_KEYWORDS):
                        errors.append(
                            f'{rel}: {cid} completion checkbox is checked [x], but status is still non-terminal "{status_value}"'
                        )
            for line in section.splitlines():
                missing = check_pending_line(line.strip())
                if missing:
                    errors.append(f'{rel}: {cid} structured pending item missing {"/".join(missing)}')
    return errors


def collect_docs(root, product_root, dev_docs):
    """Collect agent entry docs, engineering docs, and product docs for link validation."""
    paths = [root / name for name in ('AGENTS.md', 'CLAUDE.md')]
    paths = [path for path in paths if path.is_file()]
    if dev_docs.is_dir():
        paths += sorted(dev_docs.rglob('*.md'))
    if product_root.is_dir():
        paths += sorted(product_root.rglob('*.md'))
    return sorted(set(paths))


def main(argv=None):
    """CLI entrypoint; returns 0 on pass, 1 on check failure, 2 on blocked execution."""
    parser = argparse.ArgumentParser(description='SpecLock (workflow-core) documentation validator (read-only)')
    parser.add_argument('--root', default='.', help='project root directory (default: .)')
    parser.add_argument('--product-root', help='product docs root, overrides ai-workflow.yaml')
    parser.add_argument('--cards-dir', help='task cards directory, overrides ai-workflow.yaml')
    parser.add_argument('--dev-docs', help='engineering docs directory, overrides ai-workflow.yaml')
    parser.add_argument('--card-id', default=DEFAULT_CARD_ID, help='task card ID regex')
    parser.add_argument('--skip-cards', action='store_true', help='check links only, skip task cards')
    parser.add_argument('--check-config', action='store_true', help='verify configured doc paths exist')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'[docs] status=BLOCKED reason=project root does not exist: {root}', flush=True)
        return 2
    try:
        config = load_config(root)
    except ConfigError as error:
        print(f'[docs] status=BLOCKED reason=unable to load config: {error}', flush=True)
        return 2
    product_root, cards_dir, dev_docs = resolve_paths(root, args, config)
    print(
        f'[docs] paths source={config.source}; product_root={product_root.relative_to(root)}, '
        f'cards_dir={cards_dir.relative_to(root)}, dev_docs={dev_docs.relative_to(root)}',
        flush=True,
    )

    paths = collect_docs(root, product_root, dev_docs)
    link_errors = check_links(root, paths)
    card_errors = []
    if not args.skip_cards:
        if cards_dir.is_dir():
            card_errors = check_cards(root, cards_dir, args.card_id)
        else:
            print(f'[cards] directory missing, skipped: {cards_dir.relative_to(root)}', flush=True)

    glossary_errors = []
    glossary = config.get('docs.glossary')
    if glossary and not is_placeholder(glossary) and (root / glossary).is_file():
        glossary_errors = check_glossary(root, root / glossary)
        print(f'[glossary] {len(glossary_errors)} error(s)', flush=True)
    config_errors = []
    if args.check_config:
        config_errors = [f'{config.source}: missing path {item}' for item in config.missing_paths()]
        print(f'[config] {len(config_errors)} error(s)', flush=True)

    for error in link_errors + card_errors + glossary_errors + config_errors:
        print(error, file=sys.stderr)
    print(f'[links] {len(paths)} file(s), {len(link_errors)} error(s)', flush=True)
    if not args.skip_cards:
        print(f'[cards] {len(card_errors)} error(s)', flush=True)
    failed = bool(link_errors or card_errors or glossary_errors or config_errors)
    print(f'[docs] status={"CHECK_FAILED" if failed else "PASS"}', flush=True)
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
