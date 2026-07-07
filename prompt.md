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

## `web_summarize`

```
Using local-mcp, search the web for OpenAI MCP protocol, crawl the top 5 result URLs, and return concise summaries.
```

```
Using local-mcp, summarize these URLs without returning the full page content: https://example.com and https://www.python.org.
```

```
Using local-mcp, search recent news for SearXNG with categories=news, time_range=month, limit=5, crawl the result URLs, and return 2 summary sentences per source.
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

```
Using local-mcp, search the web for OpenAI MCP protocol and write 5 results to research/mcp-search-notes.pdf with write_mode=write.
```

```
Using local-mcp, search recent SearXNG news with categories=news, time_range=month, limit=5, file_type=pdf, write_mode=write, overwrite=true, and save the results to research/search-news-pdf.
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
Using local-mcp, create reports/project-brief.pdf with this content: # Project Brief

- Owner: Local MCP
- Status: PDF-ready
```

```
Using local-mcp, create reports/monthly-summary with file_type=pdf, write_mode=write, and overwrite=true. Content: # Monthly Summary

Highlights:
- Generated as a PDF
- Uses the configured LOCAL_MCP_FILE_OUTPUT_DIR destination
```

```
Using local-mcp, start a large report at reports/large-report with write_mode=write and overwrite=true. Content: # Large Report

First section content.
```

```
Using local-mcp, append this next chunk to reports/large-report with write_mode=append. Content: Second section content.
```

```
Using local-mcp, try to append to reports/monthly-summary.pdf with write_mode=append. Confirm that PDF append is rejected and explain that PDFs must be generated with write_mode=write and complete content.
```

## `schedule_task`

```
Using local-mcp, create a cron scheduled task named Morning report that runs "python scripts/morning_report.py" daily in /home/nayan/Documents/local-mcp.
```

```
Using local-mcp, create a launchd scheduled task named Weekday digest that runs "python scripts/digest.py" on weekdays.
```

```
Using local-mcp, create an n8n automation bundle named Weekly research workflow that runs "python scripts/research_digest.py" at 8 AM every Monday.
```
