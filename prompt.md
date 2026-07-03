# local-mcp MCP - Test Prompts

Use these prompts after adding `local-mcp` to Claude Desktop.

## `web_search`

```
Using local-mcp, search the web for OpenAI MCP protocol and return 5 results.
```

```
Using local-mcp, search recent news for SearXNG with categories=news, time_range=month, and limit=5.
```

```
Using local-mcp, search the web for local AI tool calling with engines=duckduckgo,brave and limit=8.
```

## `web_search_to_file`

```
Using local-mcp, search the web for OpenAI MCP protocol and write 5 results to research/mcp-search-notes.
```

```
Using local-mcp, search recent SearXNG news with categories=news, time_range=month, limit=5, and append the results to research/search-news.
```

```
Using local-mcp, search the web for local AI tool calling with engines=duckduckgo,brave and save the results to research/local-ai-tools with write_mode=write and overwrite=true.
```

## `extract_urls`

```
Using local-mcp, extract URLs from https://example.com.
```

```
Using local-mcp, extract URLs from https://quotes.toscrape.com with same_domain=true, same_path=true, and limit=25.
```

```
Using local-mcp, extract URLs from https://www.python.org with same_domain=false, same_path=false, and limit=100.
```

## `web_fetch`

```
Using local-mcp, fetch https://example.com as Markdown.
```

```
Using local-mcp, browser-render https://example.com/app and return text.
```

```
Using local-mcp, scrape .product-card elements from https://example.com/catalog and return JSON.
```

## `extract_image_text`

```
Using local-mcp, extract text from the image at C:\path\to\image.png.
```

```
Using local-mcp, extract text from the image URL https://example.com/image.png.
```

```
Using local-mcp, extract text from a base64-encoded image using lang=eng.
```

## `parse_document`

```
Using local-mcp, parse the PDF at C:\path\to\paper.pdf.
```

```
Using local-mcp, parse C:\path\to\paper.pdf with parser=pymupdf4llm and pages=1-5.
```

```
Using local-mcp, parse C:\path\to\report.pdf with parser=pdfplumber and output_format=json.
```

## `generate_file`

```
Using local-mcp, create notes/project-brief with this Markdown content: # Project Brief

- Owner: Local MCP
- Status: Draft
```

```
Using local-mcp, start a large report at reports/large-report with write_mode=write and overwrite=true. Content: # Large Report

First section content.
```

```
Using local-mcp, append this next chunk to reports/large-report with write_mode=append. Content: Second section content.
```

