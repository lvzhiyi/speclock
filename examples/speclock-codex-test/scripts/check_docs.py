#!/usr/bin/env python3
"""Standalone documentation checker (read-only, Python stdlib only; safe to commit).

Source: workflow-core 0.31.0 (source-sha256: 4aef9f8ecb4d)
Regenerate: python3 <workflow-core>/scripts/vendor_check_docs.py --output scripts/check_docs.py
"""

# === embedded: workflow_config.py ===
from pathlib import Path
import re

CONFIG_FILE = 'ai-workflow.yaml'

# Placeholder values indicating TBD or not applicable; skipped during path checks.
PLACEHOLDERS = ('TBD', 'N/A', 'none', 'None', '待确认', '无')
_PLACEHOLDER_SET = {item.lower() for item in PLACEHOLDERS}

# Schema: section -> {key: kind}; kind is 'str', 'path' (relative to project root),
# 'list' (list of strings), 'cmd' (single command or list), 'bool', or 'enum:a|b'.
SCHEMA = {
    'version': 'version',
    # Legacy switch kept only for reading old configs; gates never skip based on it.
    'engine': {'enabled': 'bool'},
    'baseline': {'required': 'list', 'scoped': 'list'},
    'docs': {
        'product_root': 'path', 'home': 'path', 'requirements': 'path', 'cards_dir': 'path',
        'overview': 'path', 'design_index': 'path', 'dev_docs': 'path', 'glossary': 'path',
    },
    # Legacy fields kept readable; external spec tools no longer drive workflow paths.
    'spec': {'tool': 'enum:openspec|none', 'dir': 'str'},
    'handoff': {'with_change': 'str', 'default': 'str'},
    'review': {'base_branch': 'str'},
    'verify': {'docs': 'cmd', 'light': 'cmd', 'standard': 'cmd', 'full': 'cmd'},
    'platforms': {'default': 'list', 'on_request': 'list', 'excluded': 'list'},
    'design': {'tool': 'str', 'source_doc': 'path'},
    'api': {'tool': 'str', 'project': 'str', 'project_id_file': 'path'},
    'code_rules_doc': 'path',
    'notes': 'list',
}

_KEY = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*):(?:\s+(.*))?$')
_UNSUPPORTED_VALUE = ('[', '{', '|', '>', '&', '*', '!', '%', '@')


def is_placeholder(value):
    """Return True when value is a recognized English or Chinese placeholder."""
    return isinstance(value, str) and value.strip().lower() in _PLACEHOLDER_SET


class ConfigError(Exception):
    """Raised when configuration cannot be parsed or fails schema validation."""

    def __init__(self, message, line=None, file=None):
        self.message = message
        self.line = line
        self.file = file
        super().__init__(self.__str__())

    def __str__(self):
        where = self.file or ''
        if self.line is not None:
            where = f'{where}:{self.line}' if where else f'line {self.line}'
        return f'{where}: {self.message}' if where else self.message


def _strip_comment(text):
    """Strip trailing comments while preserving `#` inside quotes."""
    quote = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
        elif char in '"\'':
            quote = char
        elif char == '#' and (index == 0 or text[index - 1] in ' \t'):
            return text[:index].rstrip()
    return text.rstrip()


def _scalar(raw, line):
    """Convert raw scalar text into a string or boolean."""
    raw = raw.strip()
    if raw[:1] in '"\'':
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise ConfigError('unclosed quote', line)
        return raw[1:-1]
    if raw.startswith(_UNSUPPORTED_VALUE):
        raise ConfigError(
            f'unsupported syntax "{raw[:1]}": only strings, true/false, and "- item" lists are allowed',
            line,
        )
    if raw in ('true', 'false'):
        return raw == 'true'
    return raw


def parse_yaml_subset(text):
    """Parse restricted YAML subset text into nested dict/list/scalar values."""
    lines = []
    for number, original in enumerate(text.splitlines(), 1):
        if '\t' in original[:len(original) - len(original.lstrip())]:
            raise ConfigError('tabs are not allowed for indentation', number)
        content = _strip_comment(original.strip())
        if not content:
            continue
        if content in ('---', '...') or content.startswith('? '):
            raise ConfigError('multi-document markers and complex keys are not supported', number)
        indent = len(original) - len(original.lstrip(' '))
        if indent % 2:
            raise ConfigError('indentation must be a multiple of 2 spaces', number)
        lines.append((indent, content, number))

    def block(index, indent):
        """Parse a block starting at lines[index] with indentation [indent]."""
        is_list = lines[index][1] == '-' or lines[index][1].startswith('- ')
        result = [] if is_list else {}
        while index < len(lines):
            line_indent, content, number = lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise ConfigError('unexpected indentation', number)
            item = content == '-' or content.startswith('- ')
            if item != is_list:
                raise ConfigError('cannot mix list items and key-value pairs at the same level', number)
            if is_list:
                value = content[1:].strip()
                if not value:
                    raise ConfigError('list item cannot be empty or nested', number)
                if _KEY.match(value):
                    raise ConfigError('list items must be strings, mappings are not supported', number)
                result.append(_scalar(value, number))
                index += 1
                continue
            match = _KEY.match(content)
            if not match:
                raise ConfigError('expected "key: value" (keys may use letters, digits, and underscores)', number)
            key, raw = match.group(1), match.group(2)
            if key in result:
                raise ConfigError(f'duplicate key {key}', number)
            index += 1
            if raw:
                result[key] = _scalar(raw, number)
            elif index < len(lines) and lines[index][0] > indent:
                if lines[index][0] != indent + 2:
                    raise ConfigError('child items must be indented by 2 spaces', lines[index][2])
                result[key], index = block(index, indent + 2)
            else:
                result[key] = None
        return result, index

    if not lines:
        return {}
    if lines[0][0] != 0:
        raise ConfigError('top-level item cannot be indented', lines[0][2])
    data, index = block(0, 0)
    if index < len(lines):
        raise ConfigError('unable to parse', lines[index][2])
    if not isinstance(data, dict):
        raise ConfigError('top level must be "key: value"', lines[0][2])
    return data


def _type_error(kind, value):
    """Return an error description if [value] does not match [kind], else None."""
    if value is None:
        return None
    if kind == 'bool':
        return None if isinstance(value, bool) else 'expected boolean true / false'
    if kind == 'list':
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        return None if ok else 'expected list of strings (one "- value" per line)'
    if kind == 'cmd':
        ok = isinstance(value, str) or (
            isinstance(value, list) and all(isinstance(item, str) for item in value))
        return None if ok else 'expected a command string or list of command strings'
    if kind.startswith('enum:'):
        options = kind[5:].split('|')
        return None if value in options else f'must be one of: {" / ".join(options)}'
    return None if isinstance(value, str) else 'expected string'


def validate(data):
    """Validate parsed config data against SCHEMA; return list of error strings."""
    errors = []
    if str(data.get('version')) != '1':
        errors.append('version: missing or unsupported (only version 1 is supported)')
    for key, value in data.items():
        rule = SCHEMA.get(key)
        if rule is None:
            errors.append(f'{key}: unknown configuration key')
        elif rule == 'version':
            continue
        elif isinstance(rule, dict):
            if value is None:
                continue
            if not isinstance(value, dict):
                errors.append(f'{key}: expected child mapping (indent 2 spaces on next line)')
                continue
            for sub, sub_value in value.items():
                kind = rule.get(sub)
                if kind is None:
                    errors.append(f'{key}.{sub}: unknown configuration key')
                elif _type_error(kind, sub_value):
                    errors.append(f'{key}.{sub}: {_type_error(kind, sub_value)}')
        elif _type_error(rule, value):
            errors.append(f'{key}: {_type_error(rule, value)}')
    return errors


class Config:
    """Loaded project configuration."""

    def __init__(self, data, source, root):
        self.data = data
        self.source = source
        self.root = root

    def get(self, dotted, default=None):
        """Read a dotted config key such as `docs.product_root`, stripping trailing slashes on paths."""
        value = self.data
        for part in dotted.split('.'):
            if not isinstance(value, dict) or value.get(part) is None:
                return default
            value = value[part]
        rule = SCHEMA
        for part in dotted.split('.'):
            rule = rule.get(part) if isinstance(rule, dict) else None
        return value.rstrip('/') if rule == 'path' and isinstance(value, str) else value

    def missing_paths(self):
        """List configured paths that do not exist under root, skipping placeholders and templates."""
        missing = []
        for section, rule in SCHEMA.items():
            items = rule.items() if isinstance(rule, dict) else [(None, rule)]
            for key, kind in items:
                dotted = f'{section}.{key}' if key else section
                value = self.get(dotted)
                if kind != 'path' or not isinstance(value, str):
                    continue
                if is_placeholder(value) or '{' in value:
                    continue
                if not (self.root / value).exists():
                    missing.append(f'{dotted}: {value}')
        return missing


def load(root):
    """Load ai-workflow.yaml from [root]; returns empty Config('default') if absent, raises ConfigError if invalid."""
    path = root / CONFIG_FILE
    if path.is_file():
        try:
            data = parse_yaml_subset(path.read_text(encoding='utf-8'))
        except ConfigError as error:
            raise ConfigError(error.message, error.line, CONFIG_FILE) from None
        errors = validate(data)
        if errors:
            raise ConfigError('invalid structure: ' + '; '.join(errors), None, CONFIG_FILE)
        return Config(data, CONFIG_FILE, root)
    return Config({}, 'default', root)

# === embedded: check_docs.py ===
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote

load_config = load

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
