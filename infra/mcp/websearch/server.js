#!/usr/bin/env node
// mcp-websearch — локальный MCP-сервер веб-поиска без API-ключей.
// Бэкенды: Bing Search RSS (основной) / Bing News RSS + Google News RSS (новости).
// Причина создания: коммерческие API (Exa, Tavily) отдают 403 по IP машины,
// DuckDuckGo — антибот-заглушку; Bing RSS отдаёт живую выдачу без ключей.
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const UA =
  "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0";
const TIMEOUT_MS = 20000;

const INPUT = {
  type: "object",
  properties: {
    query: {
      type: "string",
      description:
        "Поисковый запрос. Формулируй по-английски — качество выдачи выше; русский — только для новостей о России",
    },
    count: {
      type: "integer",
      description: "Число результатов, 1-20 (по умолчанию 10)",
      minimum: 1,
      maximum: 20,
    },
  },
  required: ["query"],
};

const TOOLS = [
  {
    name: "search",
    description:
      "Веб-поиск без ключей (Bing, RSS-выдача). Список результатов: заголовок, URL, сниппет. Использовать для запросов о свежей информации: события, версии, документация, новости, люди.",
    inputSchema: INPUT,
  },
  {
    name: "news",
    description:
      "Новостной поиск без ключей (Bing News RSS, запасной бэкенд — Google News RSS). Заголовок, URL, дата публикации, сниппет.",
    inputSchema: INPUT,
  },
];

function decodeXml(s) {
  return s
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => String.fromCodePoint(Number(d)))
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&amp;/g, "&");
}

// Bing News заворачивает ссылки в apiclick.aspx?...&url=<реальный URL> — распаковываем.
function unwrapBing(link) {
  try {
    const u = new URL(link);
    if (/apiclick\.aspx$/i.test(u.pathname)) {
      const real = u.searchParams.get("url");
      if (real) return real;
    }
  } catch {}
  return link;
}

function field(item, name) {
  const m = item.match(
    new RegExp(`<${name}(?:\\s[^>]*)?>([\\s\\S]*?)</${name}>`, "i"),
  );
  return m ? decodeXml(m[1].trim()) : "";
}

function parseRss(xml) {
  const items = [];
  const re = /<item(?:\s[^>]*)?>([\s\S]*?)<\/item>/gi;
  let m;
  while ((m = re.exec(xml))) {
    const body = m[1];
    const title = field(body, "title");
    const link = unwrapBing(field(body, "link"));
    if (!title && !link) continue;
    items.push({
      title,
      link,
      description: field(body, "description"),
      pubDate: field(body, "pubDate"),
    });
  }
  return items;
}

async function fetchText(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: {
        "User-Agent": UA,
        Accept: "application/rss+xml,application/xml,text/xml,*/*",
      },
    });
    return { status: res.status, text: await res.text() };
  } finally {
    clearTimeout(timer);
  }
}

function formatItems(items) {
  if (!items.length) return "Результатов не найдено.";
  return items
    .map((it, i) => {
      const head = `${i + 1}. ${it.title || "(без заголовка)"} — ${it.link}`;
      const meta = it.pubDate ? ` [${it.pubDate}]` : "";
      const tail = it.description ? `\n   ${it.description}` : "";
      return head + meta + tail;
    })
    .join("\n\n");
}

async function runSearch(query, count) {
  const url = `https://www.bing.com/search?q=${encodeURIComponent(query)}&format=rss&count=${count}&mkt=en-US&setlang=en-US`;
  const { status, text } = await fetchText(url);
  if (status !== 200) return { error: `Bing вернул HTTP ${status}: ${text.slice(0, 300)}` };
  return { text: formatItems(parseRss(text).slice(0, count)) };
}

async function runNews(query, count) {
  // qft=sortbydate="1" — сортировка по свежести (без неё Bing мешает старое и новое)
  const bing = `https://www.bing.com/news/search?q=${encodeURIComponent(query)}&format=rss&qft=sortbydate%3d%221%22&mkt=en-US&setlang=en-US`;
  let { status, text } = await fetchText(bing);
  let items = status === 200 ? parseRss(text) : [];
  let source = "Bing News";
  if (!items.length) {
    const gnews = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}`;
    ({ status, text } = await fetchText(gnews));
    items = status === 200 ? parseRss(text) : [];
    source = "Google News";
  }
  if (!items.length) return { error: `Новостей не найдено (Bing HTTP ${status})` };
  return { text: `${source}:\n\n` + formatItems(items.slice(0, count)) };
}

const server = new Server(
  { name: "websearch", version: "1.0.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const tool = TOOLS.find((t) => t.name === req.params.name);
  if (!tool) {
    return { content: [{ type: "text", text: `Unknown tool: ${req.params.name}` }], isError: true };
  }
  const args = req.params.arguments || {};
  const query = String(args.query || "").trim();
  if (!query) {
    return { content: [{ type: "text", text: "query is required" }], isError: true };
  }
  const count = Math.min(20, Math.max(1, Number(args.count) || 10));
  try {
    const r = req.params.name === "news" ? await runNews(query, count) : await runSearch(query, count);
    return { content: [{ type: "text", text: r.text }], isError: !!r.error };
  } catch (e) {
    return { content: [{ type: "text", text: String(e) }], isError: true };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("mcp-websearch: search (Bing RSS) + news (Bing/Google News RSS), без API-ключей");
