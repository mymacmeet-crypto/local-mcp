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
Using local-mcp, fetch https://example.com and use the content as evidence.
```

```
Using local-mcp, fetch https://example.com/app with max_chars=20000.
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
Using local-mcp, create reports/project-brief.docx with this content: # Project Brief

- Owner: Local MCP
- Status: Word-ready
```

```
Using local-mcp, create decks/project-brief with file_type=pptx. Content: # Project Brief

- Owner: Local MCP

## Roadmap

- MVP in Q1
- Beta in Q2
```

```
Using local-mcp, research the query "What is the Model Context Protocol?" with search_mode=smart and write the answer to research/mcp-protocol.pdf.
```

```
Using local-mcp, research the query "Compare current local LLM inference runtimes" with search_mode=deep and write the report to research/local-llm-landscape.docx with overwrite=true.
```

```
Using local-mcp, start a large report at reports/large-report with write_mode=write and overwrite=true. Content: # Large Report

First section content.
```

```
Using local-mcp, append this next chunk to reports/large-report with write_mode=append. Content: Second section content.
```

```
Using local-mcp, try to append to reports/monthly-summary.pdf with write_mode=append. Confirm that PDF append is rejected and explain that PDF, Word, and PowerPoint files must be generated with write_mode=write and complete content.
```
