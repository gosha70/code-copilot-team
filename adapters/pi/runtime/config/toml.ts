/**
 * Minimal TOML parser for CCT configuration (authored; zero dependencies).
 *
 * Supported subset (documented in the configuration reference):
 *   - comments (#), blank lines
 *   - [table] and [table.sub] headers (bare or quoted segments)
 *   - key = value with bare, quoted, or dotted keys
 *   - basic strings "…" (with \" \\ \n \t \r escapes), literal strings '…'
 *   - integers, floats, booleans
 *   - single-line arrays (nested allowed), inline tables { k = v, … }
 *
 * Not supported (parse error, by design — keep config simple):
 *   - multi-line strings, dates/times, array-of-tables [[x]]
 *
 * Errors include 1-based line numbers for actionable failures (NFR-001).
 */

export type TomlValue =
  | string
  | number
  | boolean
  | TomlValue[]
  | { [key: string]: TomlValue };

export type TomlTable = { [key: string]: TomlValue };

export class TomlError extends Error {
  line: number;
  constructor(message: string, line: number) {
    super(`TOML parse error (line ${line}): ${message}`);
    this.line = line;
  }
}

export function parseToml(input: string): TomlTable {
  const root: TomlTable = {};
  let current: TomlTable = root;
  const lines = input.split(/\r?\n/);

  for (let i = 0; i < lines.length; i++) {
    const lineNo = i + 1;
    const line = stripComment(lines[i]).trim();
    if (line === "") continue;

    if (line.startsWith("[[")) {
      throw new TomlError("array-of-tables [[…]] is not supported", lineNo);
    }

    if (line.startsWith("[")) {
      if (!line.endsWith("]")) throw new TomlError("unterminated table header", lineNo);
      const path = parseKeyPath(line.slice(1, -1).trim(), lineNo);
      current = descend(root, path, lineNo);
      continue;
    }

    const eq = findTopLevelEquals(line);
    if (eq < 0) throw new TomlError(`expected key = value, got: ${line}`, lineNo);
    const keyPath = parseKeyPath(line.slice(0, eq).trim(), lineNo);
    const rawValue = line.slice(eq + 1).trim();
    if (rawValue === "") throw new TomlError("missing value", lineNo);

    const parent = descend(current, keyPath.slice(0, -1), lineNo);
    const leaf = keyPath[keyPath.length - 1];
    if (Object.prototype.hasOwnProperty.call(parent, leaf)) {
      throw new TomlError(`duplicate key: ${keyPath.join(".")}`, lineNo);
    }
    parent[leaf] = parseValue(rawValue, lineNo);
  }

  return root;
}

function stripComment(line: string): string {
  let inBasic = false;
  let inLiteral = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"' && !inLiteral && line[i - 1] !== "\\") inBasic = !inBasic;
    else if (ch === "'" && !inBasic) inLiteral = !inLiteral;
    else if (ch === "#" && !inBasic && !inLiteral) return line.slice(0, i);
  }
  return line;
}

function parseKeyPath(raw: string, lineNo: number): string[] {
  const parts: string[] = [];
  let i = 0;
  while (i < raw.length) {
    while (raw[i] === " " || raw[i] === "\t") i++;
    if (raw[i] === '"' || raw[i] === "'") {
      const quote = raw[i];
      const end = raw.indexOf(quote, i + 1);
      if (end < 0) throw new TomlError("unterminated quoted key", lineNo);
      parts.push(raw.slice(i + 1, end));
      i = end + 1;
    } else {
      let j = i;
      while (j < raw.length && raw[j] !== "." ) j++;
      const part = raw.slice(i, j).trim();
      if (!/^[A-Za-z0-9_-]+$/.test(part)) {
        throw new TomlError(`invalid bare key segment: '${part}'`, lineNo);
      }
      parts.push(part);
      i = j;
    }
    while (raw[i] === " " || raw[i] === "\t") i++;
    if (i < raw.length) {
      if (raw[i] !== ".") throw new TomlError(`unexpected character in key: '${raw[i]}'`, lineNo);
      i++;
    }
  }
  if (parts.length === 0) throw new TomlError("empty key", lineNo);
  return parts;
}

function descend(table: TomlTable, path: string[], lineNo: number): TomlTable {
  let node: TomlTable = table;
  for (const part of path) {
    const existing = node[part];
    if (existing === undefined) {
      const child: TomlTable = {};
      node[part] = child;
      node = child;
    } else if (typeof existing === "object" && !Array.isArray(existing)) {
      node = existing as TomlTable;
    } else {
      throw new TomlError(`key '${part}' is not a table`, lineNo);
    }
  }
  return node;
}

function findTopLevelEquals(line: string): number {
  let inBasic = false;
  let inLiteral = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"' && !inLiteral && line[i - 1] !== "\\") inBasic = !inBasic;
    else if (ch === "'" && !inBasic) inLiteral = !inLiteral;
    else if (ch === "=" && !inBasic && !inLiteral) return i;
  }
  return -1;
}

export function parseValue(raw: string, lineNo: number): TomlValue {
  const [value, rest] = parseValuePrefix(raw, lineNo);
  if (rest.trim() !== "") throw new TomlError(`trailing content after value: '${rest.trim()}'`, lineNo);
  return value;
}

function parseValuePrefix(raw: string, lineNo: number): [TomlValue, string] {
  const s = raw.trim();

  if (s.startsWith('"')) {
    let out = "";
    let i = 1;
    while (i < s.length) {
      const ch = s[i];
      if (ch === "\\") {
        const next = s[i + 1];
        const map: { [k: string]: string } = { '"': '"', "\\": "\\", n: "\n", t: "\t", r: "\r" };
        if (map[next] === undefined) throw new TomlError(`unsupported escape: \\${next}`, lineNo);
        out += map[next];
        i += 2;
      } else if (ch === '"') {
        return [out, s.slice(i + 1)];
      } else {
        out += ch;
        i++;
      }
    }
    throw new TomlError("unterminated string", lineNo);
  }

  if (s.startsWith("'")) {
    const end = s.indexOf("'", 1);
    if (end < 0) throw new TomlError("unterminated literal string", lineNo);
    return [s.slice(1, end), s.slice(end + 1)];
  }

  if (s.startsWith("[")) {
    const arr: TomlValue[] = [];
    let rest = s.slice(1).trim();
    if (rest.startsWith("]")) return [arr, rest.slice(1)];
    for (;;) {
      const [value, after] = parseValuePrefix(rest, lineNo);
      arr.push(value);
      rest = after.trim();
      if (rest.startsWith(",")) {
        rest = rest.slice(1).trim();
        if (rest.startsWith("]")) return [arr, rest.slice(1)]; // trailing comma
        continue;
      }
      if (rest.startsWith("]")) return [arr, rest.slice(1)];
      throw new TomlError("expected ',' or ']' in array", lineNo);
    }
  }

  if (s.startsWith("{")) {
    const obj: TomlTable = {};
    let rest = s.slice(1).trim();
    if (rest.startsWith("}")) return [obj, rest.slice(1)];
    for (;;) {
      const eq = findTopLevelEquals(rest);
      if (eq < 0) throw new TomlError("expected key = value in inline table", lineNo);
      const keyPath = parseKeyPath(rest.slice(0, eq).trim(), lineNo);
      const [value, after] = parseValuePrefix(rest.slice(eq + 1), lineNo);
      const parent = descend(obj, keyPath.slice(0, -1), lineNo);
      parent[keyPath[keyPath.length - 1]] = value;
      rest = after.trim();
      if (rest.startsWith(",")) { rest = rest.slice(1).trim(); continue; }
      if (rest.startsWith("}")) return [obj, rest.slice(1)];
      throw new TomlError("expected ',' or '}' in inline table", lineNo);
    }
  }

  const wordEnd = s.search(/[,\]\}\s]/);
  const word = wordEnd < 0 ? s : s.slice(0, wordEnd);
  const rest = wordEnd < 0 ? "" : s.slice(wordEnd);

  if (word === "true") return [true, rest];
  if (word === "false") return [false, rest];
  if (/^[+-]?\d+$/.test(word.replace(/_/g, ""))) return [parseInt(word.replace(/_/g, ""), 10), rest];
  if (/^[+-]?(\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+)$/.test(word.replace(/_/g, ""))) {
    return [parseFloat(word.replace(/_/g, "")), rest];
  }
  throw new TomlError(`unrecognized value: '${word}' (dates and multi-line strings are not supported)`, lineNo);
}
