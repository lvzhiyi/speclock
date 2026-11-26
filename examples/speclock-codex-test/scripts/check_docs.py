#!/usr/bin/env python3
"""自包含文档规范检查脚本（只读，仅依赖 Python 标准库，可直接提交至消费项目）。

来源：workflow-core 0.28.8 (source-sha256: 44a50b1e5c8f)
重新生成：python3 <workflow-core>/scripts/vendor_check_docs.py --output scripts/check_docs.py
"""

# === embedded: workflow_config.py ===
from pathlib import Path
import re

CONFIG_FILE = 'ai-workflow.yaml'

# 占位值：表示该项未确认或不适用，路径检查时跳过。
PLACEHOLDERS = ('待确认', '无')

# 配置结构：段名 → {键名: 类型}；类型 'str' 字符串，'path' 相对项目根的路径，
# 'list' 字符串列表，'cmd' 单条命令或命令列表，'bool' 布尔值，'enum:a|b' 枚举。
SCHEMA = {
    'version': 'version',
    # 旧开关仅用于读取历史配置，执行门禁不得再依据其值跳过。
    'engine': {'enabled': 'bool'},
    'baseline': {'required': 'list', 'scoped': 'list'},
    'docs': {
        'product_root': 'path', 'home': 'path', 'requirements': 'path', 'cards_dir': 'path',
        'overview': 'path', 'design_index': 'path', 'dev_docs': 'path', 'glossary': 'path',
    },
    # 旧配置仍可加载；规格工具路径不再参与工作流或路径检查。
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


class ConfigError(Exception):
    """配置无法解析或不符合结构时抛出。

    参数 [message]：错误说明；[line]：出错行号（从 1 开始），未知时为 None；[file]：配置文件名。
    """

    def __init__(self, message, line=None, file=None):
        self.message = message
        self.line = line
        self.file = file
        super().__init__(self.__str__())

    def __str__(self):
        where = self.file or ''
        if self.line is not None:
            where = f'{where}:{self.line}' if where else f'第 {self.line} 行'
        return f'{where}: {self.message}' if where else self.message


def _strip_comment(text):
    """去掉行尾注释，引号内的 # 保留。

    参数 [text]：去掉缩进后的一行。
    返回：去掉注释和尾部空白后的内容。
    """
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
    """把标量文本转成值。

    参数 [raw]：冒号或短横线后的文本；[line]：行号，用于报错。
    返回：去掉引号的字符串，或 true / false 对应的布尔值。
    """
    raw = raw.strip()
    if raw[:1] in '"\'':
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise ConfigError('引号未闭合', line)
        return raw[1:-1]
    if raw.startswith(_UNSUPPORTED_VALUE):
        raise ConfigError(f'不支持的写法“{raw[:1]}”：只允许字符串、true / false，'
                          f'列表请逐行写 “- 值”', line)
    if raw in ('true', 'false'):
        return raw == 'true'
    return raw


def parse_yaml_subset(text):
    """解析 YAML 受限子集文本。

    参数 [text]：配置全文。
    返回：嵌套的 dict / list / 标量。
    出错时抛出 ConfigError（带行号）。
    """
    lines = []
    for number, original in enumerate(text.splitlines(), 1):
        if '\t' in original[:len(original) - len(original.lstrip())]:
            raise ConfigError('缩进不能用制表符', number)
        content = _strip_comment(original.strip())
        if not content:
            continue
        if content in ('---', '...') or content.startswith('? '):
            raise ConfigError('不支持多文档或复杂键', number)
        indent = len(original) - len(original.lstrip(' '))
        if indent % 2:
            raise ConfigError('缩进必须是 2 的倍数', number)
        lines.append((indent, content, number))

    def block(index, indent):
        """从 lines[index] 起解析一个缩进为 [indent] 的块，返回 (值, 下一个下标)。"""
        is_list = lines[index][1] == '-' or lines[index][1].startswith('- ')
        result = [] if is_list else {}
        while index < len(lines):
            line_indent, content, number = lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                raise ConfigError('缩进过深或位置不对', number)
            item = content == '-' or content.startswith('- ')
            if item != is_list:
                raise ConfigError('同一层不能混用列表项和键值', number)
            if is_list:
                value = content[1:].strip()
                if not value:
                    raise ConfigError('列表项不能为空，也不支持嵌套', number)
                if _KEY.match(value):
                    raise ConfigError('列表项只能是字符串，不支持映射', number)
                result.append(_scalar(value, number))
                index += 1
                continue
            match = _KEY.match(content)
            if not match:
                raise ConfigError('应为 “键: 值”，键只能用字母、数字和下划线', number)
            key, raw = match.group(1), match.group(2)
            if key in result:
                raise ConfigError(f'重复的键 {key}', number)
            index += 1
            if raw:
                result[key] = _scalar(raw, number)
            elif index < len(lines) and lines[index][0] > indent:
                if lines[index][0] != indent + 2:
                    raise ConfigError('子项应比上一级多缩进 2 格', lines[index][2])
                result[key], index = block(index, indent + 2)
            else:
                result[key] = None
        return result, index

    if not lines:
        return {}
    if lines[0][0] != 0:
        raise ConfigError('第一项不能缩进', lines[0][2])
    data, index = block(0, 0)
    if index < len(lines):
        raise ConfigError('无法解析', lines[index][2])
    if not isinstance(data, dict):
        raise ConfigError('顶层必须是 “键: 值”', lines[0][2])
    return data


def _type_error(kind, value):
    """检查 [value] 是否符合类型 [kind]；返回错误说明，符合时返回 None。"""
    if value is None:
        return None
    if kind == 'bool':
        return None if isinstance(value, bool) else '应为布尔值 true / false'
    if kind == 'list':
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        return None if ok else '应为字符串列表（逐行 “- 值”）'
    if kind == 'cmd':
        ok = isinstance(value, str) or (
            isinstance(value, list) and all(isinstance(item, str) for item in value))
        return None if ok else '应为一条命令或命令列表'
    if kind.startswith('enum:'):
        options = kind[5:].split('|')
        return None if value in options else f'只能是 {" / ".join(options)}'
    return None if isinstance(value, str) else '应为字符串'


def validate(data):
    """按 SCHEMA 校验配置结构。

    参数 [data]：parse_yaml_subset 的结果。
    返回：错误说明列表，空列表表示通过。未知键、类型不符、缺少或错误的 version 都会报错。
    """
    errors = []
    if str(data.get('version')) != '1':
        errors.append('version: 缺失或不支持，当前只支持 1')
    for key, value in data.items():
        rule = SCHEMA.get(key)
        if rule is None:
            errors.append(f'{key}: 未知的配置项')
        elif rule == 'version':
            continue
        elif isinstance(rule, dict):
            if value is None:
                continue
            if not isinstance(value, dict):
                errors.append(f'{key}: 应为子映射（下一行缩进 2 格写 “键: 值”）')
                continue
            for sub, sub_value in value.items():
                kind = rule.get(sub)
                if kind is None:
                    errors.append(f'{key}.{sub}: 未知的配置项')
                elif _type_error(kind, sub_value):
                    errors.append(f'{key}.{sub}: {_type_error(kind, sub_value)}')
        elif _type_error(rule, value):
            errors.append(f'{key}: {_type_error(rule, value)}')
    return errors


class Config:
    """已加载的项目配置。

    参数 [data]：配置数据（嵌套 dict）；[source]：来源说明；[root]：项目根。
    """

    def __init__(self, data, source, root):
        self.data = data
        self.source = source
        self.root = root

    def get(self, dotted, default=None):
        """按 “段.键” 读取配置值。

        参数 [dotted]：如 `docs.product_root`；[default]：未配置时的返回值。
        返回：配置值；路径类字符串去掉尾部斜杠。
        """
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
        """列出配置里写了但在项目中不存在的路径。

        返回：形如 `docs.product_root: docs/product` 的列表；占位值和含 {} 的模式跳过。
        """
        missing = []
        for section, rule in SCHEMA.items():
            items = rule.items() if isinstance(rule, dict) else [(None, rule)]
            for key, kind in items:
                dotted = f'{section}.{key}' if key else section
                value = self.get(dotted)
                if kind != 'path' or not isinstance(value, str):
                    continue
                if value in PLACEHOLDERS or '{' in value:
                    continue
                if not (self.root / value).exists():
                    missing.append(f'{dotted}: {value}')
        return missing


def load(root):
    """加载项目配置。

    参数 [root]：项目根目录（Path）。
    返回：Config；没有 ai-workflow.yaml 时返回来源为“默认值”的空配置。
    ai-workflow.yaml 存在但无法解析或结构不符时抛出 ConfigError，不回退默认值。
    """
    path = root / CONFIG_FILE
    if path.is_file():
        try:
            data = parse_yaml_subset(path.read_text(encoding='utf-8'))
        except ConfigError as error:
            raise ConfigError(error.message, error.line, CONFIG_FILE) from None
        errors = validate(data)
        if errors:
            raise ConfigError('结构不符：' + '；'.join(errors), None, CONFIG_FILE)
        return Config(data, CONFIG_FILE, root)
    return Config({}, '默认值', root)

# === embedded: check_docs.py ===
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import unquote

load_config = load

# 子需求标题：### <模块>-R<编号> 标题，例如 ### AUTH-R01 学员选择登录方式
DEFAULT_CARD_ID = r'[A-Z][A-Z0-9]*-R\d+'

# 子需求必填字段：字段名 → 匹配规则；与 templates/task-card.md 保持一致。
CARD_REQUIRED = {
    '完成勾选框': re.compile(r'^- \[[ xX]\] ', re.M),
    '来源': re.compile(r'^- (?:来源|Source)[：:]', re.M | re.I),
    '验收': re.compile(r'^- (?:验收|Acceptance)[：:]', re.M | re.I),
}

# 勾选状态与协作状态字段提取（兼容独立“协作状态：”与旧式组合“协作状态 / ...：”首段）。
CARD_CHECKED = re.compile(r'^- \[[xX]\] ', re.M)
CARD_STATUS = re.compile(
    r'^- (?:(?:协作状态|状态|Status)(?:[ \t]*/[^：:\n]+)?[：:]|\*\*(?:协作状态|状态|Status)\*\*[：:]|\*\*(?:协作状态|状态|Status)[：:]\*\*)[ \t]*(.*?)'
    r'[ \t]*(?:[；;/].*|<!--.*)?$',
    re.M | re.I,
)

# 命中以下非终态关键词时，不得同时勾选 [x]。
NON_TERMINAL_STATUS_KEYWORDS = (
    '待处理', '待确认', '待验证', '待评审', '待人工验收', '待开发', '待实施',
    '未开始', '研发中', '实施中', '进行中', '评审未通过', '受阻', '阻塞', '已暂停', '已取消',
    'pending', 'not started', 'in progress', 'implementing', 'blocked',
    'review failed', 'pending human acceptance', 'pending verification', 'cancelled',
)

# 结构化「待确认」记录（含全角竖线「｜」）必须包含的段落。
PENDING_KEYS = ('影响：', '恢复条件：')

def resolve_paths(root, args, config):
    """合并命令行参数、项目配置和默认值，得到本次检查使用的目录。

    参数 [root]：项目根目录；[args]：argparse 结果；[config]：workflow_config.Config。
    返回：(product_root, cards_dir, dev_docs)，均为绝对 Path。
    默认值：产品文档根 docs/product，任务卡目录 <产品文档根>/任务，工程规范 docs/development。
    """
    product = args.product_root or config.get('docs.product_root') or 'docs/product'
    cards = args.cards_dir or config.get('docs.cards_dir') or f'{product}/任务'
    dev = args.dev_docs or config.get('docs.dev_docs') or 'docs/development'
    return root / product, root / cards, root / dev


def check_glossary(root, path):
    """检查术语表：每个三级标题是一个词条，必须有「- 定义：」字段，词条不重名。

    参数 [root]：项目根，用于输出相对路径；[path]：术语表文件。
    返回：错误描述列表。
    """
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
            errors.append(f'{rel}: 词条重名「{term}」')
        seen.add(term)
        if not re.search(r'^- 定义[：:]\s*\S', section, re.M):
            errors.append(f'{rel}: 词条「{term}」缺少「定义」')
    return errors


def heading_slugs(text):
    """按 GitHub 规则把 Markdown 标题转成锚点列表，重名标题依次追加 -1、-2。

    参数 [text]：Markdown 全文。
    返回：所有可用锚点的集合。
    """
    seen = {}
    slugs = set()
    for title in re.findall(r'^#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
        slug = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f'{slug}-{count}')
    return slugs


def check_links(root, paths):
    """检查文档里的本地相对链接与锚点。

    参数 [root]：项目根，用于输出相对路径；[paths]：要检查的 Markdown 文件。
    返回：错误描述列表。外部链接（带协议，如 https:、mailto:）不检查。
    代码块中的链接也会被检查，与项目原有脚本行为一致。
    """
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
                errors.append(f'{rel}: 链接目标不存在 {target}')
            elif anchor and dest.suffix == '.md':
                if dest not in cache:
                    cache[dest] = heading_slugs(dest.read_text(encoding='utf-8'))
                if anchor not in cache[dest]:
                    errors.append(f'{rel}: 锚点不存在 {target}')
    return errors


def check_cards(root, cards_dir, card_id=DEFAULT_CARD_ID):
    """检查模块卡子需求的必填字段、勾选与状态一致性及结构化「待确认」格式。

    参数 [root]：项目根；[cards_dir]：任务卡目录；[card_id]：子需求编号正则。
    返回：错误描述列表。子需求小节从其 ### 标题到下一个子需求标题或二级标题为止。
    不含「｜」的自由文本「待确认：」不报错；勾选 [x] 时若协作状态仍为非终态则报错。
    """
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
                    errors.append(f'{rel}: {cid} 缺少字段「{field}」')
            if CARD_CHECKED.search(section):
                status_match = CARD_STATUS.search(section)
                if status_match:
                    status_value = status_match.group(1).strip()
                    lowered_status = status_value.lower()
                    if any(keyword in lowered_status for keyword in NON_TERMINAL_STATUS_KEYWORDS):
                        errors.append(
                            f'{rel}: {cid} 完成勾选框已勾选，但协作状态仍为非终态「{status_value}」'
                        )
            for line in re.findall(r'^- 待确认[：:].*｜.*$', section, re.M):
                missing = [key for key in PENDING_KEYS if key not in line]
                if missing:
                    errors.append(f'{rel}: {cid} 待确认记录缺少 {"/".join(missing)}')
    return errors


def collect_docs(root, product_root, dev_docs):
    """收集需要做链接检查的文档：Agent 入口、工程文档、产品文档。

    参数 [root]：项目根；[product_root]、[dev_docs]：目录（不存在则跳过）。
    返回：去重后按路径排序的 Markdown 文件列表。
    """
    paths = [root / name for name in ('AGENTS.md', 'CLAUDE.md')]
    paths = [path for path in paths if path.is_file()]
    if dev_docs.is_dir():
        paths += sorted(dev_docs.rglob('*.md'))
    if product_root.is_dir():
        paths += sorted(product_root.rglob('*.md'))
    return sorted(set(paths))


def main(argv=None):
    """命令行入口。

    参数 [argv]：命令行参数列表，None 时读取 sys.argv。
    返回：退出码，0 通过、1 检查未通过、2 执行受阻。
    """
    parser = argparse.ArgumentParser(description='workflow-core 文档规范检查（只读）')
    parser.add_argument('--root', default='.', help='项目根目录，默认当前目录')
    parser.add_argument('--product-root', help='产品文档根，覆盖工作流配置')
    parser.add_argument('--cards-dir', help='任务卡目录，覆盖工作流配置')
    parser.add_argument('--dev-docs', help='工程规范目录，覆盖工作流配置')
    parser.add_argument('--card-id', default=DEFAULT_CARD_ID, help='子需求编号正则')
    parser.add_argument('--skip-cards', action='store_true', help='只检查链接，不检查任务卡')
    parser.add_argument('--check-config', action='store_true',
                        help='额外检查配置里的路径是否存在')
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'[docs] status=BLOCKED reason=项目根不存在 {root}', flush=True)
        return 2
    try:
        config = load_config(root)
    except ConfigError as error:
        print(f'[docs] status=BLOCKED reason=配置无法读取 {error}', flush=True)
        return 2
    product_root, cards_dir, dev_docs = resolve_paths(root, args, config)
    print(f'[docs] 路径来源：{config.source}；产品文档根={product_root.relative_to(root)}，'
          f'任务卡={cards_dir.relative_to(root)}，工程规范={dev_docs.relative_to(root)}', flush=True)

    paths = collect_docs(root, product_root, dev_docs)
    link_errors = check_links(root, paths)
    card_errors = []
    if not args.skip_cards:
        if cards_dir.is_dir():
            card_errors = check_cards(root, cards_dir, args.card_id)
        else:
            print(f'[cards] 任务卡目录不存在，跳过：{cards_dir.relative_to(root)}', flush=True)

    glossary_errors = []
    glossary = config.get('docs.glossary')
    if glossary and glossary not in ('待确认', '无') and (root / glossary).is_file():
        glossary_errors = check_glossary(root, root / glossary)
        print(f'[glossary] {len(glossary_errors)} 个错误', flush=True)
    config_errors = []
    if args.check_config:
        config_errors = [f'{config.source}: 路径不存在 {item}' for item in config.missing_paths()]
        print(f'[config] {len(config_errors)} 个错误', flush=True)

    for error in link_errors + card_errors + glossary_errors + config_errors:
        print(error, file=sys.stderr)
    print(f'[links] {len(paths)} 个文件，{len(link_errors)} 个错误', flush=True)
    if not args.skip_cards:
        print(f'[cards] {len(card_errors)} 个错误', flush=True)
    failed = bool(link_errors or card_errors or glossary_errors or config_errors)
    print(f'[docs] status={"CHECK_FAILED" if failed else "PASS"}', flush=True)
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
