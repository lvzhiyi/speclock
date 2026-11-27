#!/usr/bin/env python3
"""Load and validate project workflow configuration ai-workflow.yaml (read-only, Python stdlib only).

Uses a strict YAML subset parsed locally without PyYAML:
- Mapping `key: value`; when value is empty, the next line indents 2 spaces for a child mapping or list;
- String lists `- value`;
- Scalars: strings (optional single/double quotes), true / false;
- Full-line or trailing `#` comments (preserving `#` inside quotes).
Unsupported: inline [] / {}, multiline strings | >, anchors & *, multi-document ---, tab indentation.
Raises ConfigError with line numbers on unsupported syntax instead of falling back silently.

When ai-workflow.yaml is absent at project root, callers use default paths.
"""
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
